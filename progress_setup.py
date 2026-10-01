"""Desktop lifecycle and reversible reader pairing for local progress sync."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
from urllib.parse import urlsplit
from urllib.error import HTTPError

import lua_settings
import progress_sync
import setup


def book_documents(mount):
    documents = {}
    for index, path in enumerate(mount.rglob('*.epub')):
        if index >= 2000: raise setup.SetupError('Too many EPUBs for automatic migration. Use a smaller reader library for pairing.')
        path = setup.guarded(path)
        digest = hashlib.md5()
        with path.open('rb') as source:
            for offset in [0] + [1024 << (2*i) for i in range(11)]:
                source.seek(offset); digest.update(source.read(1024))
        documents[digest.hexdigest()] = path.name
    return documents


def remote_base(settings):
    value = (settings.get('custom_server') or 'https://sync.koreader.rocks:443').rstrip('/')
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path or not parsed.hostname:
        raise setup.SetupError('The old progress server address is not supported for automatic migration. Your reader settings are unchanged.')
    if parsed.scheme != 'https': setup.private_url(value)
    return value


class ProgressSetup:
    def progress_directory(self):
        directory = setup.guarded(self.app / 'progress_sync')
        for name in ('credentials.json','positions.sqlite3','positions.sqlite3-wal','positions.sqlite3-shm'):
            setup.guarded(directory / name)
        return directory

    def progress_account(self):
        path = self.progress_directory() / 'credentials.json'
        if not path.is_file(): raise setup.SetupError('Turn on reading-position sync first.')
        return json.loads(path.read_text())

    def progress_authenticated(self, endpoint=None):
        saved = self.state.get('progress_sync', {})
        if not saved.get('port'): return False
        try:
            base = endpoint or f'http://127.0.0.1:{saved["port"]}'
            health = json.loads(setup.http(base + '/healthcheck', timeout=2, maximum=4096))
            if health.get('service') != 'reader-bridge-progress': return False
            account = self.progress_account()
            result = json.loads(setup.http(base + '/users/auth', headers=progress_sync.auth_headers(account), timeout=2, maximum=4096))
            return result.get('username') == account['username']
        except (OSError,ValueError,setup.SetupError): return False

    def progress_status(self):
        saved = self.state.get('progress_sync', {})
        rows, uploads, error = [], [], ''
        try:
            path = self.progress_directory() / 'positions.sqlite3'
            rows = progress_sync.read_archive(path)
            uploads = progress_sync.read_uploads(path)
        except (OSError,ValueError,sqlite3.Error,setup.SetupError):
            error = 'Saved reading positions could not be read. Your files are retained.'
        return {'enabled':bool(saved.get('enabled')), 'healthy':bool(saved.get('enabled')) and self.progress_authenticated(),
                'endpoint':saved.get('endpoint',''), 'port':saved.get('port',8085),
                'kindle_paired':bool(saved.get('kindle')) and saved['kindle'].get('endpoint') == saved.get('endpoint'),
                'xteink_paired':bool(saved.get('xteink')) and saved['xteink'].get('endpoint') == saved.get('endpoint'),
                'book_count':len(rows), 'uploads':uploads, 'error':error,
                'verified':bool(saved.get('verified'))}

    def start_progress(self, endpoint, port=None):
        self.stable_installation()
        if sys.platform != 'darwin': raise setup.SetupError('Background reading-position sync requires macOS.')
        saved = self.state.get('progress_sync', {})
        port = port or saved.get('port') or next((p for p in range(8085,8100) if setup.available(p)), None)
        if type(port) is not int or not 1024 <= port <= 65535: raise setup.SetupError('Choose an available port for reading-position sync.')
        if saved.get('port') and saved['port'] != port and (saved.get('kindle') or saved.get('xteink')):
            raise setup.SetupError('Keep the saved progress port so paired readers can still connect.')
        self.check_port('progress_sync',port)
        self.assert_loaded_ownership('progress_sync')
        advertised = setup.private_url(endpoint or saved.get('endpoint',''))
        host = urlsplit(advertised).hostname
        advertised = f'http://{host}:{port}'
        directory = self.progress_directory()
        progress_sync.credentials(directory)
        progress_sync.Store(directory/'positions.sqlite3')
        self.install_file(directory/'progress_sync.py', (setup.SOURCE/'progress_sync.py').read_bytes())
        self.state['progress_sync'] = {**saved, 'enabled':True, 'port':port, 'endpoint':advertised, 'verified':bool(saved.get('verified')) and saved.get('endpoint') == advertised}
        self.save()
        self.launch('progress_sync',[sys.executable,directory/'progress_sync.py','--state-dir',directory,'--port',str(port)],directory)
        for _ in range(30):
            if self.progress_authenticated(): break
            time.sleep(.25)
        else: raise setup.SetupError('Reading-position sync could not start. Saved positions are retained; check Advanced and retry.')
        if not self.progress_authenticated(advertised):
            raise setup.SetupError('The Mac address is not reachable. Choose a reachable LAN address in Advanced before pairing.')
        self.refresh_position_backups()

    def refresh_position_backups(self):
        if not self.state.get('cloud_backup',{}).get('enabled'): return
        self.assert_ownership('cloud_backup'); self.assert_loaded_ownership('cloud_backup')
        self.stop_owned('cloud_backup')
        directory = setup.guarded(self.app/'cloud_backup')
        for name in ('archive_backup.py','progress_sync.py'):
            self.install_file(directory/name, (setup.SOURCE/name).read_bytes())
        self.launch('cloud_backup',[sys.executable,directory/'archive_backup.py','--state-dir',directory],directory)

    def stop_progress(self):
        self.stop_owned('progress_sync')
        path = self.agent_path('progress_sync')
        if self.owned('progress_sync'):
            self.backup(path); path.unlink()
        self.state.setdefault('progress_sync',{})['enabled'] = False
        self.state['progress_sync'].pop('agent',None)
        self.save()

    def paired_progress_endpoint(self):
        endpoint = setup.private_url(self.state.get('progress_sync',{}).get('endpoint',''))
        if not self.state.get('progress_sync',{}).get('enabled') or not self.progress_authenticated(endpoint):
            raise setup.SetupError('Start reading-position sync on a reachable Mac address before pairing.')
        return endpoint

    def migrate_kindle_progress(self, mount, root, previous, endpoint):
        settings = previous.get('settings',{})
        account = self.progress_account()
        if (settings.get('username') == account['username']
                and settings.get('userkey') == progress_sync.auth_headers(account)['x-auth-key']):
            return None  # Re-pairing the same account must retain pending offline work.
        documents = book_documents(mount)
        rows = {}
        if settings.get('username') and settings.get('userkey') and remote_base(settings) != endpoint:
            base = remote_base(settings)
            headers = {'x-auth-user':settings['username'], 'x-auth-key':settings['userkey'], 'Accept':'application/vnd.koreader.v1+json'}
            # Probe even for an empty library before changing any device settings.
            try:
                setup.http(base+'/users/auth',headers=headers,timeout=8,maximum=4096)
                for document, name in documents.items():
                    old_id = hashlib.md5(name.encode()).hexdigest() if settings.get('checksum_method') == 1 else document
                    try: row = json.loads(setup.http(base+'/syncs/progress/'+old_id,headers=headers,timeout=8,maximum=progress_sync.MAX_BODY))
                    except HTTPError as exc:
                        if exc.code == 404: continue
                        raise
                    if not row.get('progress'): continue
                    row['document'] = document
                    # Old servers without timestamps cannot safely claim a newer location.
                    row.setdefault('timestamp',0)
                    row.setdefault('metadata',{'filename':name})
                    rows[document] = progress_sync.validate(row,saved=True)
            except (OSError,ValueError,setup.SetupError) as exc:
                raise setup.SetupError('Could not copy positions from the old sync server. Reader settings are unchanged; check internet access and retry.') from exc
        queue_path = setup.guarded(root/'settings/kosync_queue.lua')
        if queue_path.is_file():
            queue = lua_settings.loads(queue_path.read_text())
            filename_ids = {hashlib.md5(name.encode()).hexdigest():doc for doc,name in documents.items()}
            for item in queue.values():
                if not isinstance(item,dict): raise setup.SetupError('Unrecognized offline progress queue. Preserve it and sync KOReader before pairing.')
                item = dict(item)
                if settings.get('checksum_method') == 1:
                    if item.get('document') not in filename_ids: raise setup.SetupError('An offline position refers to a missing book. Sync KOReader before pairing.')
                    item['document'] = filename_ids[item['document']]
                item['timestamp'] = item.get('queued_at',0)
                item = progress_sync.validate(item,saved=True)
                old = rows.get(item['document'])
                if old is None or item['timestamp'] > old['timestamp']: rows[item['document']] = item
        # Immutable local migration receipt excludes credentials.
        self.install_file(self.app/'backups'/('progress-migration-'+str(time.time_ns())+'.json'),json.dumps(list(rows.values()),ensure_ascii=False).encode())
        progress_sync.Store(self.progress_directory()/'positions.sqlite3').seed(rows.values(), newer=True)
        return queue_path if queue_path.is_file() else None

    def pair_progress_kindle(self, mount):
        endpoint = self.paired_progress_endpoint()
        mount = setup.guarded(Path(mount).expanduser())
        root = next((p for p in [mount/'koreader',mount/'.adds/koreader'] if (p/'reader.lua').is_file()),None)
        if not root: raise setup.SetupError('Connect your Kindle in USB drive mode with KOReader closed, then select its folder.')
        path = setup.guarded(root/'settings/kosync.lua')
        old = path.read_bytes() if path.is_file() else None
        try: previous = lua_settings.loads(old.decode()) if old else {'settings':{}}
        except (ValueError,UnicodeError) as exc: raise setup.SetupError('KOReader settings use an unsupported format. No reader files were changed.') from exc
        if not isinstance(previous.get('settings'),dict): raise setup.SetupError('KOReader progress settings are invalid. No reader files were changed.')
        # Preserve the exact previous account and source before any network migration.
        if old: self.backup(path)
        queue_path = self.migrate_kindle_progress(mount,root,previous,endpoint)
        account = self.progress_account()
        settings = previous['settings']
        settings.update(custom_server=endpoint, username=account['username'], userkey=progress_sync.auth_headers(account)['x-auth-key'], checksum_method=0, send_metadata=True)
        settings.setdefault('auto_sync', True)
        settings.setdefault('sync_forward',1); settings.setdefault('sync_backward',1)
        updates = [(path,lua_settings.dumps(previous).encode())]
        if queue_path: updates.append((queue_path,b'return {}\n'))
        originals = [(p,p.read_bytes() if p.is_file() else None) for p,_ in updates]
        try:
            for p,data in updates: self.install_file(p,data)
        except BaseException:
            for p,data in originals:
                if data is not None:
                    try: setup.atomic_write(p,data)
                    except OSError: pass
            raise
        if old:
            source = lua_settings.loads(old.decode())['settings']
            if source.get('username') and source.get('username') != account['username']:
                self.state['progress_sync']['migration_source'] = {'username':source['username'],'server':remote_base(source)}
        self.state['progress_sync']['kindle'] = {'mount':str(mount),'endpoint':endpoint,'paired_at':datetime.now(timezone.utc).isoformat()}
        self.state['progress_sync']['verified'] = False
        self.save()

    def pair_progress_xteink(self, mount=None, device_url=None):
        endpoint = self.paired_progress_endpoint()
        if self.state['progress_sync'].get('kindle',{}).get('endpoint') != endpoint:
            raise setup.SetupError('Connect Kindle progress first so its existing server positions are copied before switching Xteink.')
        if bool(mount) == bool(device_url): raise setup.SetupError('Choose one Xteink connection method.')
        path = '/.crosspoint/koreader.json'
        client = setup.Xteink(setup.private_url(device_url),self) if device_url else None
        if client:
            if json.loads(client.get('/api/status')).get('device') != 'xteink_x4_pro':
                raise setup.SetupError('The connected device is not an Xteink X4 Pro.')
            old = client.read_file(path)
        else:
            mount = setup.guarded(Path(mount).expanduser())
            if not (mount/'.crosspoint').is_dir(): raise setup.SetupError('Select the Xteink SD card with its .crosspoint folder.')
            local = setup.guarded(mount/path.lstrip('/'))
            old = local.read_bytes() if local.is_file() else None
        previous = json.loads(old) if old else {}
        if not isinstance(previous,dict): raise setup.SetupError('Unrecognized Xteink settings. No reader files were changed.')
        account = self.progress_account()
        if previous.get('username') and previous['username'] != account['username']:
            source = self.state['progress_sync'].get('migration_source',{})
            old_server = previous.get('serverUrl') or ('https://sync.koreader.rocks:443' if previous.get('cfgVersion',1) < 2 else 'https://sync.crosspointreader.com')
            if '://' not in old_server: old_server = 'http://' + old_server
            def origin(value):
                url = urlsplit(value)
                return (url.scheme,url.hostname,url.port or (443 if url.scheme == 'https' else 80),url.path.rstrip('/'))
            if previous['username'] != source.get('username') or origin(old_server) != origin(source.get('server','')):
                raise setup.SetupError('Xteink uses a different previous progress account than Kindle. Its settings are unchanged; sync both readers to the same old account before migrating.')
        previous.pop('password_obf',None)
        previous.update(cfgVersion=2, username=account['username'], password=account['password'], serverUrl=endpoint,matchMethod=1,sendMetadata=True)
        previous.setdefault('syncBehavior',0)
        data = (json.dumps(previous,indent=2)+'\n').encode()
        if client: client.put_file(path,data,old)
        else: self.install_file(local,data)
        # Firmware imports the legacy password field and resaves it obfuscated.
        self.state['progress_sync']['xteink'] = {'url':device_url or '', 'endpoint':endpoint, 'paired_at':datetime.now(timezone.utc).isoformat()}
        self.state['progress_sync']['verified'] = False
        self.save()
