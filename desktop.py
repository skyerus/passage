#!/usr/bin/env python3
"""Native app JSON bridge. Status caps highlights at 500; count/export cover all live quotes."""
import argparse
import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import plistlib
import re
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.error import HTTPError

# The backend may live inside a signed .app, including when invoked directly.
sys.dont_write_bytecode = True

import setup
from collector import Store, initialize, item_key

MAX_REQUEST = 64 * 1024
MAX_IMPORT = 16 * 1024 * 1024
MAX_EXPORT = 64 * 1024 * 1024
HIGHLIGHTS_LIMIT = 500


def text_arg(value, name):
    if not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > 4096 or '\x00' in value:
        raise setup.SetupError('Provide a valid ' + name + '.')
    return value


def port_arg(value):
    if type(value) is not int or not 1024 <= value <= 65535:
        raise setup.SetupError('Choose an integer port from 1024 to 65535.')
    return value


def bool_arg(value, name):
    if type(value) is not bool:
        raise setup.SetupError(name + ' must be true or false.')
    return value


class Desktop(setup.Bridge):
    def owned(self, kind):
        path = self.agent_path(kind)
        if not path.exists() or self.state.get(kind, {}).get('agent') != str(path):
            return False
        try:
            setup.guarded(path)
            spec = plistlib.loads(path.read_bytes())
            args = spec.get('ProgramArguments', [])
            directory = self.app / kind
            return (spec.get('Label') == setup.LABELS[kind]
                    and spec.get('WorkingDirectory') == str(directory)
                    and isinstance(args, list) and len(args) >= 2
                    and (str(directory / 'collector.py') in args if kind == 'collector'
                         else args[0] == str(directory / 'venv/bin/cps')))
        except (OSError, ValueError, plistlib.InvalidFileException):
            return False

    def assert_ownership(self, kind):
        if self.agent_path(kind).exists() and not self.owned(kind):
            raise setup.SetupError('An unowned or changed Reader Bridge service exists. Resolve it before installing or stopping this service.')

    def assert_loaded_ownership(self, kind):
        loaded = subprocess.run(['launchctl', 'print', f'gui/{os.getuid()}/{setup.LABELS[kind]}'], capture_output=True, text=True, timeout=5)
        if loaded.returncode != 0:
            return
        if not self.owned(kind):
            raise setup.SetupError('An unowned Reader Bridge service is already loaded. Existing services were left alone.')
        spec = plistlib.loads(self.agent_path(kind).read_bytes())
        def field(name):
            value = re.search(r'^\s*' + re.escape(name) + r' = (.+)\s*$', loaded.stdout, re.MULTILINE)
            return value.group(1).strip() if value else None
        if (field('path') != str(self.agent_path(kind))
                or field('program') != spec['ProgramArguments'][0]
                or field('working directory') != spec['WorkingDirectory']):
            raise setup.SetupError('The loaded service differs from this app’s saved service. Existing services were left alone; resolve the conflicting job first.')

    def authenticated(self, port, endpoint=None):
        token_path = self.app / 'collector/data/token'
        if not token_path.is_file():
            return False
        try:
            base = endpoint or f'http://127.0.0.1:{port}'
            health = json.loads(setup.http(base + '/healthz', timeout=2, maximum=4096))
            if health.get('service') != 'reader-bridge' or health.get('status') != 'ok':
                return False
            # Invalid empty batch authenticates but cannot insert or delete data.
            try:
                setup.http(base + '/v1/highlights', b'{}', headers={'Authorization': 'Bearer ' + token_path.read_text().strip(), 'Content-Type': 'application/json'}, timeout=2, maximum=4096)
            except HTTPError as exc:
                return exc.code == 400 and json.loads(exc.read(4096)).get('error') == 'invalid highlight batch'
        except (OSError, ValueError, setup.SetupError):
            pass
        return False

    def check_port(self, kind, port):
        port_arg(port)
        self.assert_ownership(kind)
        if setup.available(port):
            return
        if self.owned(kind) and self.state.get(kind, {}).get('port') == port:
            if kind == 'collector' and self.authenticated(port):
                return
            if kind == 'library' and self.library_listener_owned(port):
                return
        raise setup.SetupError(f'Port {port} is occupied by an unverified service. Choose another port; existing services were left alone.')

    def library_listener_owned(self, port):
        # A matching plist cannot establish ownership of a listening socket.
        # Require launchd's loaded path and PID to match the actual listener.
        if sys.platform != 'darwin':
            return False
        try:
            loaded = subprocess.run(['launchctl', 'print', f'gui/{os.getuid()}/{setup.LABELS["library"]}'], capture_output=True, text=True, timeout=5)
            listener = subprocess.run(['/usr/sbin/lsof', '-nP', f'-iTCP:{port}', '-sTCP:LISTEN', '-Fp'], capture_output=True, text=True, timeout=5)
            pid = re.search(r'^\s*pid = (\d+)\s*$', loaded.stdout, re.MULTILINE)
            path = re.search(r'^\s*path = (.+)\s*$', loaded.stdout, re.MULTILINE)
            pids = {line[1:] for line in listener.stdout.splitlines() if re.fullmatch(r'p\d+', line)}
            return (loaded.returncode == listener.returncode == 0 and bool(pid) and bool(path)
                    and path.group(1).strip() == str(self.agent_path('library')) and pids == {pid.group(1)})
        except (OSError, subprocess.TimeoutExpired):
            return False

    def launch(self, kind, arguments, directory, start=True):
        self.assert_ownership(kind)
        self.assert_loaded_ownership(kind)
        super().launch(kind, arguments, directory, start)

    def stop_owned(self, kind):
        self.assert_ownership(kind)
        self.assert_loaded_ownership(kind)
        if self.owned(kind):
            super().stop_owned(kind)

    @staticmethod
    def stable_installation():
        if str(setup.SOURCE).startswith('/Volumes/'):
            raise setup.SetupError('Move Reader Bridge to Applications and reopen it before installing background services.')

    def collector(self, *args, **kwargs):
        self.stable_installation()
        super().collector(*args, **kwargs)

    def start_local(self, port, disable=False):
        self.stable_installation()
        if sys.platform != 'darwin':
            raise setup.SetupError('Background collector installation requires macOS.')
        existing = self.state.get('collector', {})
        changed_port = existing.get('port') is not None and existing['port'] != port
        if changed_port and (self.state.get('kindle', {}).get('installed') or self.state.get('xteink', {}).get('paired')):
            raise setup.SetupError('This collector already has paired readers. Keep its current port so their saved pairing addresses continue to work.')
        self.check_port('collector', port)
        if changed_port and self.state.get('url'):
            from urllib.parse import urlsplit
            host = urlsplit(setup.private_url(self.state['url'])).hostname
            self.state['url'] = f'http://{host}:{port}'
        if existing.get('archive') and not disable and not existing.get('backup_disabled'):
            self.collector(existing['archive'], port=port)
            return
        target = self.app / 'collector'
        self.save()
        for filename in ('collector.py', 'db.py'):
            self.install_file(target / filename, (setup.SOURCE / filename).read_bytes())
        directory, _ = initialize(target / 'data')
        Store(directory / 'inbox.sqlite3')
        self.state['collector'] = {**existing, 'port': port, 'backup_disabled': bool(disable or existing.get('backup_disabled')), 'mode': 'local'}
        self.save()
        self.launch('collector', [sys.executable, target / 'collector.py', 'serve', '--state-dir', directory, '--host', '0.0.0.0', '--port', str(port), '--no-publish'], target)
        for _ in range(30):
            if self.authenticated(port):
                return
            time.sleep(.25)
        raise setup.SetupError('Collector could not start. Check the private service logs and retry; your inbox is retained.')

    def live_rows(self):
        path = self.app / 'collector/data/inbox.sqlite3'
        if not path.exists():
            return [], 0
        setup.guarded(path)
        # Store's constructor initializes storage: status must never call it.
        con = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            con.execute('PRAGMA query_only=ON')
            con.execute('BEGIN')
            deleted = {r[0] for r in con.execute('SELECT quote_key FROM tombstones')}
            pending = con.execute('SELECT count(*) FROM inbox WHERE published IS NULL OR published!=revision').fetchone()[0]
            pending += con.execute('SELECT count(*) FROM tombstones WHERE published=0').fetchone()[0]
            rows = {}
            for source, payload in con.execute('SELECT source,payload FROM inbox ORDER BY source,device,id'):
                item = json.loads(payload)
                if item.get('deleted'):
                    continue
                key = item_key(item)
                if key not in deleted and key not in rows:
                    rows[key] = {'id': key, 'title': item['book_title'], 'author': item['author'], 'text': item['text'], 'source': source, 'created_at': item.get('created_at', '')}
            return sorted(rows.values(), key=lambda row: (row['created_at'], row['id']), reverse=True), pending
        finally:
            con.close()

    def status(self, query=''):
        service = self.state.get('collector', {})
        kindle = self.state.get('kindle', {})
        xteink = self.state.get('xteink', {})
        library = self.state.get('library', {})
        port = port_arg(service.get('port', 8084))
        warnings = []
        try:
            rows, pending = self.live_rows()
        except (OSError, ValueError, KeyError, sqlite3.Error):
            rows, pending = [], 0
            warnings.append('The local inbox could not be read. Data was left unchanged; retry or inspect the private app directory.')
        count = len(rows)
        if query:
            needle = query.casefold()
            rows = [row for row in rows if any(needle in row[key].casefold() for key in ('title', 'author', 'text'))]
        mounts = []
        try:
            for mount in Path('/Volumes').iterdir():
                if mount.is_symlink():
                    continue
                if any((mount / p / 'reader.lua').is_file() for p in ('koreader', '.adds/koreader')):
                    mounts.append({'name': mount.name, 'path': str(mount), 'kind': 'kindle'})
                elif (mount / '.crosspoint').is_dir():
                    mounts.append({'name': mount.name, 'path': str(mount), 'kind': 'xteink'})
        except OSError:
            pass
        addresses = []
        # Prefer the active network over VM/bridge addresses returned first by
        # hostname resolution. No connection or packet to an outside host needed.
        if sys.platform == 'darwin':
            try:
                route = subprocess.run(['/sbin/route', '-n', 'get', 'default'], capture_output=True, text=True, timeout=3)
                interface = re.search(r'^\s*interface:\s*([A-Za-z0-9]+)\s*$', route.stdout, re.MULTILINE)
                if route.returncode == 0 and interface:
                    address = subprocess.run(['/usr/sbin/ipconfig', 'getifaddr', interface.group(1)], capture_output=True, text=True, timeout=3)
                    if address.returncode == 0:
                        addresses.append(setup.private_url(f'http://{address.stdout.strip()}:{port}'))
            except (OSError, subprocess.TimeoutExpired, setup.SetupError):
                pass
        host = socket.gethostname().split('.')[0]
        if re.fullmatch(r'[A-Za-z0-9-]+', host):
            addresses.append(f'http://{host}.local:{port}')
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                candidate = f'http://{info[4][0]}:{port}'
                try:
                    setup.private_url(candidate)
                except setup.SetupError:
                    continue
                if candidate not in addresses:
                    addresses.append(candidate)
        except OSError:
            pass
        healthy = self.authenticated(port) if service else False
        if service and not healthy:
            warnings.append('Collector is stopped or unreachable. Readers retain pending uploads until it is available.')
        mode = 'github' if service.get('archive') and not service.get('backup_disabled') else 'local'
        return {'service': {'installed': self.owned('collector'), 'healthy': healthy, 'port': port, 'mode': mode, 'archive': service.get('archive', '') if mode == 'github' else '', 'pending_backup': pending if mode == 'github' else 0},
                'kindle': {'paired': bool(kindle.get('installed')), 'connected': bool(kindle.get('mount') and any((Path(kindle['mount']) / p / 'reader.lua').is_file() for p in ('koreader', '.adds/koreader'))), 'mount': kindle.get('mount', '')},
                'xteink': {'paired': bool(xteink.get('paired')), 'firmware_staged': bool(xteink.get('firmware_staged')), 'url': xteink.get('device_url') or ''},
                'mounts': mounts, 'highlights': rows[:HIGHLIGHTS_LIMIT], 'highlight_count': count, 'highlights_matches': len(rows), 'highlights_limit': HIGHLIGHTS_LIMIT,
                'progress_verified': bool(self.state.get('progress', {}).get('verified')), 'endpoint': self.state.get('url') or (addresses[0] if addresses else ''), 'addresses': addresses, 'warnings': warnings,
                'library': {'installed': self.owned('library'), 'port': library.get('port', 8083), 'books': library.get('books', '')}}

    def endpoint(self, value):
        endpoint = setup.private_url(text_arg(value, 'collector LAN address'))
        if not self.authenticated(self.state.get('collector', {}).get('port', 8084), endpoint):
            raise setup.SetupError('That LAN address does not reach this collector. Start it and check your address, firewall and Wi-Fi before pairing.')
        return endpoint

    def mutate(self, command, args):
        extra = {}
        if command == 'start_collector':
            self.start_local(port_arg(args.get('port', 8084)))
        elif command == 'stop_collector':
            if sys.platform != 'darwin':
                raise setup.SetupError('Stopping a background service requires macOS.')
            self.assert_ownership('collector')
            self.assert_loaded_ownership('collector')
            if self.owned('collector'):
                path = self.agent_path('collector')
                result = subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{setup.LABELS["collector"]}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if result.returncode and self.authenticated(self.state.get('collector', {}).get('port', 8084)):
                    raise setup.SetupError('The collector could not stop. Retry after checking macOS background service permissions.')
                self.backup(path)
                path.unlink()
                self.state['collector'].pop('agent', None)
                self.save()
        elif command == 'pair_kindle':
            self.kindle(text_arg(args.get('mount'), 'Kindle volume'), self.endpoint(args.get('endpoint')))
        elif command == 'pair_xteink':
            if args.get('model_confirmed') is not True:
                raise setup.SetupError('Confirm that the device is an Xteink X4 Pro before pairing or staging firmware.')
            firmware = bool_arg(args.get('firmware', False), 'firmware')
            mount, url = args.get('mount'), args.get('device_url')
            if bool(mount) == bool(url):
                raise setup.SetupError('Select either an SD card volume or an Xteink LAN address.')
            self.xteink(mount=text_arg(mount, 'SD volume') if mount else None, device_url=text_arg(url, 'Xteink LAN address') if url else None, url=self.endpoint(args.get('endpoint')), firmware=firmware, model='xteink_x4_pro')
        elif command == 'import_clippings':
            path = setup.guarded(Path(text_arg(args.get('path'), 'clippings file')).expanduser())
            if not path.is_file() or path.stat().st_size > MAX_IMPORT:
                raise setup.SetupError('Select a My Clippings.txt file no larger than 16 MiB.')
            if not self.authenticated(self.state.get('collector', {}).get('port', 8084)):
                raise setup.SetupError('Start your local collector before importing clippings.')
            from import_clippings import parse_clippings
            with path.open('rb') as source:
                content = source.read(MAX_IMPORT + 1)
            if len(content) > MAX_IMPORT:
                raise setup.SetupError('Select a My Clippings.txt file no larger than 16 MiB.')
            rows = parse_clippings(content.decode('utf-8-sig'))
            port = self.state['collector']['port']
            token = (self.app / 'collector/data/token').read_text().strip()
            for row in rows:
                payload = json.dumps({'source': 'koreader', 'device_id': 'kindle-clippings-import', 'highlights': [row]}).encode()
                result = json.loads(setup.http(f'http://127.0.0.1:{port}/v1/highlights', payload, headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, maximum=4096, timeout=15))
                if result.get('accepted') != [row['id']]:
                    raise setup.SetupError('Collector did not acknowledge every import. Retry safely; duplicates are ignored.')
        elif command == 'export':
            path = setup.guarded(Path(text_arg(args.get('path'), 'export file')).expanduser())
            if path == self.app or self.app in path.parents or path.exists():
                raise setup.SetupError('Choose a new export filename outside the private app directory.')
            rows, _ = self.live_rows()
            data = (json.dumps(rows, ensure_ascii=False, indent=2) + '\n').encode()
            if len(data) > MAX_EXPORT:
                raise setup.SetupError('Export exceeds 64 MiB. Preserve the inbox and use a database export tool.')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
            except BaseException:
                path.unlink(missing_ok=True)
                raise
            extra['exported'] = len(rows)
        elif command == 'verify_progress':
            self.state['progress'] = {'verified': bool_arg(args.get('verified'), 'verified'), 'server': 'https://sync.crosspointreader.com'}
            self.save()
        elif command == 'configure_backup':
            archive = text_arg(args.get('archive'), 'personal archive OWNER/REPO')
            create = bool_arg(args.get('create', False), 'create')
            self.collector(archive, create=create, port=port_arg(self.state.get('collector', {}).get('port', 8084)))
            self.state['collector']['backup_disabled'] = False
            self.state['collector']['mode'] = 'github'
            self.save()
        elif command == 'disable_backup':
            if not self.state.get('collector'):
                raise setup.SetupError('Start the collector first.')
            self.start_local(port_arg(self.state['collector'].get('port', 8084)), disable=True)
        elif command == 'install_library':
            self.stable_installation()
            self.library(text_arg(args.get('books'), 'Calibre library folder'), port_arg(args.get('port', 8083)))
        else:
            raise setup.SetupError('Unknown desktop command.')
        return {**self.status(), **extra}


@contextlib.contextmanager
def mutation_lock(app):
    app = setup.guarded(app)
    app.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = setup.guarded(app / '.desktop.lock')
    with lock.open('a') as handle:
        os.chmod(lock, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise setup.SetupError('Another setup action is running. Wait for it to finish and retry.')
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def execute(request, app=setup.DEFAULT_APP, agent_dir=None):
    if not isinstance(request, dict):
        raise setup.SetupError('Request must be a JSON object.')
    command = text_arg(request.get('command'), 'command')
    commands = {'status', 'start_collector', 'stop_collector', 'pair_kindle', 'pair_xteink', 'import_clippings', 'export', 'verify_progress', 'configure_backup', 'disable_backup', 'install_library'}
    if command not in commands:
        raise setup.SetupError('Unknown desktop command.')
    app = setup.guarded(Path(app).expanduser())
    if command == 'status':
        query = request.get('query', '')
        if not isinstance(query, str) or len(query) > 1000 or '\x00' in query:
            raise setup.SetupError('Search must be text no longer than 1000 characters.')
        return Desktop(app, agent_dir=agent_dir).status(query)
    with mutation_lock(app):
        return Desktop(app, agent_dir=agent_dir).mutate(command, request)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-dir', type=Path, default=setup.DEFAULT_APP)
    args = parser.parse_args(argv)
    try:
        body = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(body) > MAX_REQUEST:
            raise setup.SetupError('Desktop request exceeds 64 KiB.')
        request = json.loads(body)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            data = execute(request, args.app_dir)
        response = {'ok': True, 'data': data}
    except Exception as exc:
        response = {'ok': False, 'error': str(exc) if isinstance(exc, setup.SetupError) else 'Action could not complete. Check your inputs, connectivity and folder permissions, then retry; completed checkpoints are preserved.'}
    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
