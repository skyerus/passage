#!/usr/bin/env python3
"""Guided macOS setup for Reader Bridge. Python 3.10+, standard library only."""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib import request, parse, error

SOURCE = Path(__file__).resolve().parent
DEFAULT_APP = Path.home() / 'Library/Application Support/Reader Bridge'
LABELS = {'collector': 'com.readerbridge.collector', 'library': 'com.readerbridge.library'}
CALIBRE_WEB = '0.6.27'
BUILD_OVERRIDE = b'[env:x4pro]\nlib_deps =\n  ${base.lib_deps}\n  greiman/SdFat @ 2.3.1\n'


class SetupError(Exception):
    pass


def run(command, **kwargs):
    result = subprocess.run([str(x) for x in command], capture_output=True, text=True, **kwargs)
    if result.returncode:
        # Commands may contain credentials or return personal book data. Never echo them.
        raise SetupError(f'{Path(command[0]).name} failed (exit {result.returncode}); check its installation/account access.')
    return result.stdout


def private_url(value):
    value = value.rstrip('/')
    try:
        parsed = parse.urlsplit(value)
        port = parsed.port if parsed.port is not None else 80
    except ValueError:
        raise SetupError('Invalid LAN URL.')
    if parsed.scheme != 'http' or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or not 1 <= port <= 65535:
        raise SetupError('Use an HTTP LAN address without a path, credentials or query.')
    host = parsed.hostname or ''
    if re.fullmatch(r'[A-Za-z0-9-]+\.local', host):
        return value
    try:
        address = ipaddress.IPv4Address(host)
        if any(address in ipaddress.ip_network(net) for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
            return value
    except ValueError:
        pass
    raise SetupError('Use an RFC1918 private IPv4 address or a single-name .local host on your trusted LAN.')


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise SetupError('Redirect refused; check the device or collector address.')


def http(url, data=None, method=None, headers=None, maximum=32 * 1024 * 1024, timeout=300):
    opener = request.build_opener(NoRedirect(), request.ProxyHandler({}))
    req = request.Request(url, data=data, method=method, headers=headers or {})
    with opener.open(req, timeout=timeout) as response:
        content = response.read(maximum + 1)
        if len(content) > maximum:
            raise SetupError('Response exceeds expected size.')
        return content


def available(port):
    if not 1024 <= port <= 65535:
        raise SetupError('Choose a port from 1024 to 65535.')
    with socket.socket() as sock:
        try:
            sock.bind(('0.0.0.0', port))
        except OSError:
            return False
    return True


def guarded(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise SetupError('Refusing a symlink destination: ' + str(path))
    return path


def atomic_write(path, data, mode=0o600):
    path = guarded(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            os.chmod(temporary, mode)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
        if path.read_bytes() != data:
            raise SetupError('Readback verification failed: ' + str(path))
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def yes(prompt):
    return input(prompt + ' [y/N] ').strip().lower() == 'y'


class Bridge:
    def __init__(self, app=DEFAULT_APP, dry_run=False, agent_dir=None):
        self.app = guarded(Path(app).expanduser())
        self.dry_run = dry_run
        self.agent_dir = guarded(agent_dir or Path.home() / 'Library/LaunchAgents')
        self.state_path = self.app / 'state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}

    def save(self):
        if self.dry_run:
            return
        self.app.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.app, 0o700)
        atomic_write(self.state_path, (json.dumps(self.state, indent=2) + '\n').encode())

    def backup(self, path):
        path = guarded(path)
        if path.exists():
            name = time.strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(4) + '-' + path.name
            target = self.app / 'backups' / name
            atomic_write(target, path.read_bytes())
            os.chmod(target.parent, 0o700)
            return target

    def install_file(self, target, content):
        target = guarded(target)
        if target.exists() and target.read_bytes() == content:
            return
        self.backup(target)
        atomic_write(target, content)

    def agent_path(self, kind):
        return self.agent_dir / (LABELS[kind] + '.plist')

    def launch(self, kind, arguments, directory, start=True):
        if sys.platform != 'darwin':
            raise SetupError('Installing background services requires macOS.')
        label = LABELS[kind]
        agent = self.agent_path(kind)
        if agent.exists() and self.state.get(kind, {}).get('agent') != str(agent):
            raise SetupError('An unowned Reader Bridge agent already exists. Inspect it before selecting another app directory.')
        logs = self.app / 'logs'
        logs.mkdir(mode=0o700, parents=True, exist_ok=True)
        spec = {'Label': label, 'ProgramArguments': [str(x) for x in arguments], 'WorkingDirectory': str(directory),
                'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10, 'Umask': 63,
                'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin', 'PYTHONUNBUFFERED': '1'},
                'StandardOutPath': str(logs / (kind + '.log')), 'StandardErrorPath': str(logs / (kind + '-error.log'))}
        # Persist ownership intent before touching the plist. Interrupted lint or
        # bootstrap can then resume without mistaking our file for another app's.
        self.state.setdefault(kind, {})['agent'] = str(agent)
        self.save()
        self.install_file(agent, plistlib.dumps(spec))
        run(['plutil', '-lint', str(agent)])
        domain = f'gui/{os.getuid()}'
        if start:
            subprocess.run(['launchctl', 'bootout', domain + '/' + label], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            run(['launchctl', 'bootstrap', domain, str(agent)])
        self.state.setdefault(kind, {})['agent'] = str(agent)
        self.save()

    def check_port(self, kind, port):
        if available(port):
            return
        existing = self.state.get(kind, {})
        agent = self.agent_path(kind)
        if existing.get('port') == port and existing.get('agent') == str(agent) and agent.exists():
            return  # Updating our own registered service.
        raise SetupError(f'Port {port} is occupied. Choose another port; existing services were left alone.')

    def gh(self, *args, data=None):
        gh = shutil.which('gh')
        if not gh:
            raise SetupError('Install GitHub CLI from https://cli.github.com and run gh auth login first.')
        return run([gh, *args], input=json.dumps(data) if data is not None else None, timeout=90)

    def collector(self, archive, create=False, port=8084, allow_public=False):
        if not archive or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', archive):
            raise SetupError('Select your personal archive explicitly with --archive OWNER/REPO.')
        if archive.lower() in ('skyerus/reader-bridge', 'skyerus/kindle-highlights'):
            raise SetupError('Select your own separate personal archive, not the public source or example archive.')
        if self.dry_run:
            print(f'Would verify {archive}, install a collector on port {port}, and preserve its existing inbox/token.')
            return
        existing = self.state.get('collector', {})
        if existing.get('archive') and existing['archive'].lower() != archive.lower():
            raise SetupError('This inbox belongs to a different archive. Choose a fresh --app-dir; archive migration is not supported.')
        if sys.platform != 'darwin':
            raise SetupError('Collector installation requires macOS; use --dry-run elsewhere.')
        self.check_port('collector', port)
        self.gh('auth', 'status')
        if create and self.state.get('created_archive') != archive:
            # --create-archive is explicit consent. Record successful creation
            # before initialization so a subsequent API failure is resumable.
            self.gh('repo', 'create', archive, '--private')
            self.state['created_archive'] = archive
            self.save()
        if self.state.get('created_archive') == archive:
            created = json.loads(self.gh('repo', 'view', archive, '--json', 'defaultBranchRef'))
            if not created.get('defaultBranchRef'):
                details = json.loads(self.gh('api', f'repos/{archive}'))
                branch_name = details.get('default_branch', 'main')
                # A create-only Contents request has no SHA; it cannot overwrite
                # a highlights.json somebody added after repository creation.
                self.gh('api', f'repos/{archive}/contents/highlights.json', '--method', 'PUT', '--input', '-', data={'message': 'Initialize personal highlight archive', 'content': base64.b64encode(b'[]\n').decode(), 'branch': branch_name})
            self.state.pop('created_archive', None)
            self.save()
        repo = json.loads(self.gh('repo', 'view', archive, '--json', 'nameWithOwner,isPrivate,defaultBranchRef'))
        if not repo['isPrivate'] and not allow_public:
            raise SetupError('This archive is public. Select a private archive or explicitly pass --allow-public.')
        branch = (repo.get('defaultBranchRef') or {}).get('name')
        if not branch:
            raise SetupError('Existing archive needs a default branch and highlights.json JSON array before setup.')
        if existing.get('branch') and existing['branch'] != branch:
            raise SetupError('The archive default branch changed. Preserve this inbox and resolve the branch change before resuming.')
        blob = json.loads(self.gh('api', f'repos/{archive}/contents/highlights.json?ref={parse.quote(branch, safe="")}'))
        content = json.loads(base64.b64decode(blob['content']))
        if not isinstance(content, list) or any(not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ('highlight', 'book_title', 'author')) for row in content):
            raise SetupError('Archive highlights.json has an incompatible schema; no service installed.')
        self.save()
        target = self.app / 'collector'
        for filename in ('collector.py', 'db.py'):
            self.install_file(target / filename, (SOURCE / filename).read_bytes())
        run([sys.executable, str(target / 'collector.py'), 'init', '--state-dir', str(target / 'data')])
        self.state['collector'] = {**self.state.get('collector', {}), 'archive': archive, 'branch': branch, 'port': port}
        self.save()
        args = [sys.executable, target / 'collector.py', 'serve', '--state-dir', target / 'data', '--host', '0.0.0.0', '--port', str(port), '--repo', archive, '--branch', branch, '--gh', shutil.which('gh')]
        self.launch('collector', args, target)
        self.wait_health(port)
        print('Collector running. Quotes publish to your selected archive; token stays in the private app directory.')

    @staticmethod
    def wait_health(port):
        for _ in range(30):
            try:
                if json.loads(http(f'http://127.0.0.1:{port}/healthz', timeout=2)).get('service') == 'reader-bridge':
                    return
            except (OSError, ValueError, KeyError):
                time.sleep(.25)
        raise SetupError('Collector did not become healthy. Run doctor and inspect its local error log.')

    def pairing(self, kind, url, previous=None):
        url = private_url(url or self.state.get('url', ''))
        token_path = self.app / 'collector/data/token'
        if not token_path.exists():
            raise SetupError('Install the collector before pairing a device.')
        token = token_path.read_text().strip()
        previous = previous or {}
        device_id = previous.get('device_id') or self.state.get('devices', {}).get(kind) or kind + '-' + secrets.token_hex(12)
        self.state.setdefault('devices', {})[kind] = device_id
        self.state['url'] = url
        self.save()
        return {'url': url, 'token': token, 'device_id': device_id}

    def kindle(self, mount, url=None):
        mount = guarded(Path(mount).expanduser())
        candidates = [mount / 'koreader', mount / '.adds/koreader']
        root = next((p for p in candidates if (p / 'reader.lua').is_file()), None)
        if root is None:
            raise SetupError('No installed KOReader found here. Follow docs/SETUP.md for your exact Kindle model/firmware, exit KOReader, then reconnect USB.')
        if self.dry_run:
            print('Would back up changed plugin/config files, preserve queue, and install into ' + str(root))
            return
        config = root / 'settings/sharedhighlights-config.json'
        previous = json.loads(config.read_text()) if config.exists() else {}
        pairing = self.pairing('koreader', url, previous)
        for source in sorted((SOURCE / 'koreader/sharedhighlights.koplugin').glob('*.lua')):
            self.install_file(root / 'plugins/sharedhighlights.koplugin' / source.name, source.read_bytes())
        self.install_file(config, (json.dumps({**previous, **pairing}, indent=2) + '\n').encode())
        self.state['kindle'] = {'installed': True, 'mount': str(mount)}
        self.save()
        print('Plugin and pairing verified. Queue preserved. Eject Kindle, restart KOReader, enable Wi-Fi, then open a book.')

    def xteink(self, mount=None, device_url=None, url=None, firmware=False, model=None):
        if model != 'xteink_x4_pro':
            raise SetupError('This release supports only explicitly confirmed --model xteink_x4_pro. Do not flash another model.')
        if not mount and not device_url:
            raise SetupError('Choose --mount SD_PATH or --xteink-url http://DEVICE-LAN-IP.')
        if mount and device_url:
            raise SetupError('Choose one Xteink connection method.')
        if self.dry_run:
            print('Would validate X4 Pro, back up/pair config and optionally stage checksum-verified firmware; flashing remains manual.')
            return
        client = Xteink(private_url(device_url), self) if device_url else None
        if client:
            status = json.loads(client.get('/api/status'))
            if status.get('device') != model:
                raise SetupError('Device API model does not match X4 Pro; nothing uploaded.')
            old = client.read_file('/.crosspoint/highlight-sync.json')
        else:
            mount = guarded(Path(mount).expanduser())
            if not (mount / '.crosspoint').is_dir():
                raise SetupError('Selected SD card has no .crosspoint directory. Confirm the device and initialize CrossPoint first.')
            path = guarded(mount / '.crosspoint/highlight-sync.json')
            old = path.read_bytes() if path.exists() else None
        previous = json.loads(old) if old else {}
        config = self.pairing('crosspoint', url, previous)
        data = (json.dumps({'endpoint': config['url'] + '/v1/highlights', 'token': config['token'], 'device_id': config['device_id']}, indent=2) + '\n').encode()
        if client:
            client.put_file('/.crosspoint/highlight-sync.json', data, old)
        else:
            self.install_file(path, data)
        if firmware:
            manifest = json.loads((SOURCE / 'firmware.json').read_text())
            spec = manifest.get('devices', {}).get(model)
            if not spec:
                raise SetupError('No pinned firmware source available for this model.')
            firmware_bytes = self.build_firmware(spec)
            filename = spec.get('filename', 'reader-bridge-x4-pro.bin')
            if Path(filename).name != filename or not filename.endswith('.bin'):
                raise SetupError('Invalid firmware filename in release manifest.')
            if client:
                client.put_file('/' + filename, firmware_bytes, client.read_file('/' + filename))
            else:
                self.install_file(mount / filename, firmware_bytes)
            print('Firmware staged and fully readback-verified. On the X4 Pro, open Settings → System → SD Card Firmware Update and confirm this .bin manually. Do not interrupt power.')
        self.state['xteink'] = {'paired': True, 'firmware_staged': firmware, 'device_url': device_url}
        self.save()
        print('Pairing verified. Close File Transfer to resume reading and automatic sync.')

    def build_firmware(self, spec):
        commit = spec.get('commit', '')
        if not re.fullmatch('[a-f0-9]{40}', commit) or spec.get('environment') != 'x4pro' or spec.get('repository') != 'https://github.com/skyerus/crosspoint-reader.git' or spec.get('platformio') != '6.2.0':
            raise SetupError('Unsupported firmware source manifest; refusing an unpinned build.')
        directory = self.app / 'builds' / commit
        source = directory / 'source'
        venv = directory / 'venv'
        output = source / '.pio/build/x4pro/firmware.bin'
        receipt = directory / 'build.json'
        print('Building pinned X4 Pro source locally. First build downloads toolchains/dependencies and can take several minutes.')
        directory.mkdir(parents=True, exist_ok=True)
        if not (venv / 'bin/python').exists():
            run([sys.executable, '-m', 'venv', str(venv)], timeout=120)
        run([venv / 'bin/python', '-m', 'pip', 'install', 'platformio==6.2.0'], timeout=600)
        if not source.exists():
            staging = Path(tempfile.mkdtemp(prefix='checkout-', dir=directory))
            try:
                run(['git', 'clone', '--no-checkout', spec['repository'], staging], timeout=600)
                run(['git', '-C', staging, 'checkout', '--detach', commit], timeout=120)
                staging.rename(source)
            except Exception:
                # Preserve a failed checkout for diagnostics; a fresh staging path
                # next time makes interrupted clone/checkout resumable.
                raise
        if run(['git', '-C', source, 'rev-parse', 'HEAD']).strip() != commit:
            raise SetupError('Cached source is not the pinned commit. Preserve your edits and choose a fresh app directory.')
        override = source / 'platformio.local.ini'
        if override.exists() and override.read_bytes() != BUILD_OVERRIDE:
            raise SetupError('An unrecognized local PlatformIO override exists. Preserve it elsewhere before building the pinned firmware.')
        atomic_write(override, BUILD_OVERRIDE)
        if run(['git', '-C', source, 'status', '--porcelain', '--untracked-files=no']).strip():
            raise SetupError('Cached firmware source was modified; refusing to build an unreviewed variant.')
        run(['git', '-C', source, 'submodule', 'update', '--init', '--recursive'], timeout=600)
        submodules = run(['git', '-C', source, 'submodule', 'status', '--recursive'])
        if any(line.startswith(('+', '-', 'U')) for line in submodules.splitlines()):
            raise SetupError('Firmware submodule revision mismatch; refusing an unpinned build.')
        fingerprint = {'commit': commit, 'environment': 'x4pro', 'platformio': '6.2.0', 'override_sha256': hashlib.sha256(BUILD_OVERRIDE).hexdigest()}
        if output.exists() and receipt.exists():
            data = output.read_bytes()
            cached = json.loads(receipt.read_text())
            if all(cached.get(k) == v for k, v in fingerprint.items()) and cached.get('sha256') == hashlib.sha256(data).hexdigest():
                return data
        build_log = directory / 'build.log'
        print('Build progress log: ' + str(build_log), flush=True)
        with build_log.open('w') as log:
            os.chmod(build_log, 0o600)
            result = subprocess.run([str(venv / 'bin/pio'), 'run', '-e', 'x4pro'], cwd=source, stdout=log, stderr=subprocess.STDOUT, timeout=1800, env={**os.environ, "PLATFORMIO_CORE_DIR": str(self.app / "platformio")})
        if result.returncode or not output.is_file():
            raise SetupError('Firmware build failed. Inspect the private builds directory build.log and resume setup.')
        data = output.read_bytes()
        if not data or len(data) > 32 * 1024 * 1024:
            raise SetupError('Firmware output has an unexpected size.')
        atomic_write(receipt, json.dumps({**fingerprint, 'sha256': hashlib.sha256(data).hexdigest()}).encode())
        return data

    def library(self, books, port=8083):
        books = Path(books).expanduser().resolve()
        if not (books / 'metadata.db').is_file():
            raise SetupError('Select an existing Calibre library containing metadata.db. Install Calibre from calibre-ebook.com, create a library and add DRM-free EPUBs first.')
        if self.dry_run:
            print(f'Would install Calibre-Web {CALIBRE_WEB} in a private venv on port {port}, using your selected library without converting EPUBs.')
            return
        if sys.platform != 'darwin':
            raise SetupError('Library installation requires macOS; use --dry-run elsewhere.')
        self.check_port('library', port)
        self.save()
        directory = self.app / 'library'
        venv = directory / 'venv'
        if not (venv / 'bin/python').exists():
            run([sys.executable, '-m', 'venv', str(venv)], timeout=120)
        self.stop_owned('library')
        run([venv / 'bin/python', '-m', 'pip', 'install', 'calibreweb==' + CALIBRE_WEB], timeout=600)
        database = directory / 'app.db'
        credentials_path = directory / 'admin.json'
        configured = directory / 'configured.json'
        if not configured.exists():
            if credentials_path.exists():
                credentials = json.loads(credentials_path.read_text())
                if credentials.get('username') != 'admin' or len(credentials.get('password', '')) < 24:
                    raise SetupError('Invalid initialization credentials; library remains unexposed.')
            else:
                credentials = {'username': 'admin', 'password': secrets.token_urlsafe(24)}
                atomic_write(credentials_path, (json.dumps(credentials) + '\n').encode())
            # Official -s initializes configuration, changes admin password, and
            # exits before starting the server. Secret travels on stdin, not argv.
            initializer = 'import sys; from pathlib import Path; p=sys.stdin.read(); d=Path(sys.argv[1]); sys.argv=["cps","-p",str(d),"-g",str(d.with_name("gdrive.db")),"-o",str(d.with_name("library.log")),"-s","admin:"+p]; from calibreweb.__main__ import main; main()'
            run([venv / 'bin/python', '-c', initializer, database], input=credentials['password'], timeout=120)
        self.backup(database)
        with sqlite3.connect(database) as con:
            con.execute('UPDATE settings SET config_calibre_dir=?, config_calibre_web_title=?, config_uploading=1, config_upload_formats=?, config_anonbrowse=0, config_public_reg=0, config_remote_login=0, config_embed_metadata=0, config_port=?, config_external_port=?', (str(books), 'Reader Bridge Library', 'epub', port, port))
            password_hash = con.execute('SELECT password FROM user WHERE name=?', ('admin',)).fetchone()
            if not password_hash:
                raise SetupError('Administrator missing; library remains unexposed.')
        # Fail closed even if someone reverted the stored administrator to a
        # known default between setup runs. Existing chosen passwords are preserved.
        check = 'import sys,json; from werkzeug.security import check_password_hash; h=json.load(sys.stdin); sys.exit(1 if any(check_password_hash(h,p) for p in ("admin123","admin","password","")) else 0)'
        run([venv / 'bin/python', '-c', check], input=json.dumps(password_hash[0]))
        os.chmod(database, 0o600)
        atomic_write(configured, json.dumps({'version': CALIBRE_WEB, 'secure_admin': True}).encode())
        self.state['library'] = {**self.state.get('library', {}), 'books': str(books), 'port': port, 'version': CALIBRE_WEB}
        self.save()
        self.launch('library', [venv / 'bin/cps', '-p', database, '-g', directory / 'gdrive.db', '-o', directory / 'library.log', '-i', '0.0.0.0'], directory)
        print(f'Library installed on port {port}. Administrator credentials: {directory / "admin.json"}. Open its web UI, create a reader account, then add http://MAC-LAN-IP:{port}/opds on each device. Metadata embedding is disabled; use identical original EPUB bytes on both readers.')

    def progress(self):
        print('Progress uses the existing CrossPoint Sync service: https://sync.crosspointreader.com')
        print('1. Xteink Settings → Sync: use https://sync.crosspointreader.com, create/sign in to your account, choose content matching and Ask Every Time.\n2. KOReader Progress sync → Custom sync server: enter the same URL and sign in to the same account; select Binary document matching and automatic sync as desired.\n3. Open the exact same EPUB bytes on both devices. Xteink Upload Local sends your current location; Apply Remote receives it. Test both directions before marking complete. Progress credentials and highlight tokens are separate.')
        if self.dry_run:
            return
        if yes('Have you configured both readers and verified a position round-trip?'):
            self.state['progress'] = {'verified': True, 'server': 'https://sync.crosspointreader.com'}
            self.save()
        else:
            print('Progress setup remains pending. Resume with python3 setup.py progress.')

    def import_clippings(self, path):
        from import_clippings import parse_clippings
        rows = parse_clippings(Path(path).read_text(encoding='utf-8-sig'))
        if self.dry_run:
            print(f'Would import {len(rows)} English-format Kindle highlights to the local collector; no quote text printed.')
            return
        collector = self.state.get('collector', {})
        if not collector:
            raise SetupError('Install the collector first.')
        token = (self.app / 'collector/data/token').read_text().strip()
        # One record also keeps escaped, near-limit Unicode excerpts below the
        # collector's request limit. Imports remain idempotent across retries.
        for row in rows:
            batch = [row]
            payload = json.dumps({'source': 'koreader', 'device_id': 'kindle-clippings-import', 'highlights': batch}).encode()
            result = json.loads(http(f'http://127.0.0.1:{collector["port"]}/v1/highlights', payload, headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}))
            if set(result.get('accepted', [])) != {row['id'] for row in batch}:
                raise SetupError('Collector did not acknowledge every import record. Rerun safely; duplicates are ignored.')
        print(f'{len(rows)} highlights stored locally for publication. Unsupported/non-English clippings are not guessed.')

    def doctor(self):
        report = {'macos': sys.platform == 'darwin', 'python': sys.version.split()[0], 'gh_installed': bool(shutil.which('gh')), 'services': {},
                  'kindle_installed': bool(self.state.get('kindle', {}).get('installed')), 'xteink_paired': bool(self.state.get('xteink', {}).get('paired')), 'progress_verified': bool(self.state.get('progress', {}).get('verified'))}
        for kind in LABELS:
            port = self.state.get(kind, {}).get('port')
            if port:
                report['services'][kind] = {'port': port, 'listening': not available(port), 'agent_exists': self.agent_path(kind).exists()}
        if self.state.get('collector'):
            status = report['services']['collector']
            try:
                health = json.loads(http(f'http://127.0.0.1:{status["port"]}/healthz', timeout=2))
                status['healthy'] = health.get('status') == 'ok' and health.get('service') == 'reader-bridge'
            except (OSError, ValueError):
                status['healthy'] = False
            database = self.app / 'collector/data/inbox.sqlite3'
            if database.exists():
                con = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
                try:
                    status['pending_uploads'] = con.execute('SELECT count(*) FROM inbox WHERE published IS NULL OR published!=revision').fetchone()[0]
                    status['pending_deletions'] = con.execute('SELECT count(*) FROM tombstones WHERE published=0').fetchone()[0]
                finally:
                    con.close()
            publication = self.app / 'collector/data/publication-status.json'
            if publication.exists():
                value = json.loads(publication.read_text())
                status['publication'] = {k: value[k] for k in ('status', 'attempted_at', 'error_type') if k in value}
        print(json.dumps(report, indent=2))

    def stop_owned(self, kind):
        agent = self.agent_path(kind)
        if self.state.get(kind, {}).get('agent') == str(agent) and agent.exists():
            subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{LABELS[kind]}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def uninstall(self):
        if self.dry_run:
            print('Would unload only owned Reader Bridge LaunchAgents; retain archives, inbox, backups, books and device queues.')
            return
        if sys.platform != 'darwin':
            raise SetupError('Service removal requires macOS.')
        for kind, label in LABELS.items():
            agent = self.agent_path(kind)
            if self.state.get(kind, {}).get('agent') != str(agent):
                continue
            subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{label}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if agent.exists():
                self.backup(agent); agent.unlink()
            self.state[kind].pop('agent', None)
        self.save()
        print('Owned background services removed. Personal data, device installations and backups retained; resume setup to reinstall.')


class Xteink:
    def __init__(self, url, bridge):
        self.url, self.bridge = url, bridge
    def get(self, suffix):
        return http(self.url + suffix)
    def read_file(self, path):
        try:
            return self.get('/download?path=' + parse.quote(path, safe=''))
        except error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
    def put_file(self, path, data, old):
        if old == data:
            return
        if old is not None:
            self.bridge.install_file(self.bridge.app / 'backups' / (secrets.token_hex(8) + '-' + Path(path).name), old)
            # Existing firmware refuses overwrite. Back up before deleting this exact target.
            response = http(self.url + '/delete?path=' + parse.quote(path, safe=''), b'', method='POST')
        boundary = 'ReaderBridge' + secrets.token_hex(16)
        name = Path(path).name
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + data + f'\r\n--{boundary}--\r\n'.encode())
        http(self.url + '/upload?path=' + parse.quote(str(Path(path).parent), safe=''), body, headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
        received = self.read_file(path)
        if received is None or hashlib.sha256(received).digest() != hashlib.sha256(data).digest():
            raise SetupError('Device readback hash mismatch. Backup is retained; do not flash this file.')


def wizard(bridge):
    if bridge.dry_run:
        print('Plan: prerequisites -> private archive -> collector -> Kindle model/KOReader checkpoint -> plugin -> X4 Pro pairing/verified firmware -> progress account walkthrough -> optional Calibre-Web -> verification. No files, services, devices or repositories changed.')
        return
    print('Reader Bridge: resumable setup. Your Mac and readers must share a trusted LAN. An asleep Mac is unavailable; readers retain pending uploads. Press Ctrl-C to pause safely.')
    if sys.platform != 'darwin':
        raise SetupError('This setup supports macOS. --dry-run and tests also run elsewhere.')
    if not shutil.which('gh'):
        raise SetupError('Install Python 3.10+ and GitHub CLI from https://cli.github.com, run gh auth login, then rerun this command.')
    archive = bridge.state.get('collector', {}).get('archive') or input('Personal archive (your GitHub OWNER/REPO): ').strip()
    create = False
    if not bridge.state.get('collector'):
        create = yes('Create this as a NEW PRIVATE repository? Choose no to use an existing archive with highlights.json')
    port = int(input(f'Collector port [{bridge.state.get("collector", {}).get("port", 8084)}]: ') or bridge.state.get('collector', {}).get('port', 8084))
    bridge.collector(archive, create, port)
    url = input(f'Collector LAN URL [{bridge.state.get("url", "http://YOUR-MAC.local:" + str(port))}]: ').strip() or bridge.state.get('url', '')
    private_url(url)
    # Confirm that the chosen advertised address actually reaches this token-owning service.
    if json.loads(http(url + '/healthz', timeout=5)).get('status') != 'ok':
        raise SetupError('The advertised LAN URL did not reach the collector. Check IP, firewall and Wi-Fi.')
    bridge.state['url'] = url; bridge.save()
    print('Kindle checkpoint: follow docs/SETUP.md for your exact model and firmware. Jailbreak/KOReader installation is model-specific; this installer never flashes a Kindle.')
    if yes('KOReader is installed, exited, and Kindle is connected by USB. Install the highlight plugin now?'):
        bridge.kindle(input('Kindle mounted volume path: ').strip(), url)
    print('Xteink checkpoint: this firmware supports only X4 Pro. Open CrossPoint File Transfer on your trusted LAN.')
    if yes('Pair an X4 Pro now?'):
        device_url = input('X4 Pro File Transfer URL (http://LAN-IP): ').strip()
        firmware = yes('Stage the pinned custom X4 Pro firmware for manual on-device installation?')
        bridge.xteink(device_url=device_url, url=url, firmware=firmware, model='xteink_x4_pro')
        if firmware:
            if yes('Has the on-device firmware update completed successfully?'):
                bridge.state['xteink']['firmware_confirmed'] = True; bridge.save()
    bridge.progress()
    if yes('Install an optional local Calibre-Web library?'):
        print('First use Calibre to create a library and add your DRM-free EPUBs. Select that library folder; original EPUB bytes stay unchanged.')
        bridge.library(input('Calibre library folder: ').strip(), int(input('Library port [8083]: ') or '8083'))
    if yes('Import existing English-format Kindle My Clippings.txt highlights?'):
        bridge.import_clippings(input('Path to My Clippings.txt: ').strip())
    bridge.doctor()
    print('Setup checkpoints saved. Test one highlight and one deletion from each reader, then a progress round-trip. Rerun this command for skipped steps; status shows installed components.')


def main(argv=None):
    if sys.version_info < (3, 10):
        print("Reader Bridge requires Python 3.10 or newer. Install it from python.org, then rerun setup.py.", file=sys.stderr)
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-dir', type=Path, default=DEFAULT_APP)
    parser.add_argument('--dry-run', action='store_true', help='Describe actions without changing files, services, devices or repositories.')
    subs = parser.add_subparsers(dest='command')
    for name in ('wizard', 'doctor', 'status', 'progress', 'uninstall'):
        subs.add_parser(name)
    collector = subs.add_parser('collector')
    collector.add_argument('--archive', required=True)
    collector.add_argument('--create-archive', action='store_true')
    collector.add_argument('--allow-public', action='store_true')
    collector.add_argument('--port', type=int, default=8084)
    kindle = subs.add_parser('kindle'); kindle.add_argument('--mount', required=True); kindle.add_argument('--url')
    xteink = subs.add_parser('xteink'); xteink.add_argument('--mount'); xteink.add_argument('--xteink-url'); xteink.add_argument('--url'); xteink.add_argument('--model', required=True); xteink.add_argument('--firmware', action='store_true')
    library = subs.add_parser('library'); library.add_argument('--books', required=True); library.add_argument('--port', type=int, default=8083)
    clippings = subs.add_parser('import-clippings'); clippings.add_argument('path')
    args = parser.parse_args(argv)
    try:
        bridge = Bridge(args.app_dir, args.dry_run)
        command = args.command or 'wizard'
        if sys.platform != 'darwin' and command not in ('doctor', 'status') and not args.dry_run:
            raise SetupError('Reader Bridge installation supports macOS. Help, doctor, status and --dry-run work on other platforms.')
        if command == 'wizard': wizard(bridge)
        elif command in ('doctor', 'status'): bridge.doctor()
        elif command == 'collector': bridge.collector(args.archive, args.create_archive, args.port, args.allow_public)
        elif command == 'kindle': bridge.kindle(args.mount, args.url)
        elif command == 'xteink': bridge.xteink(args.mount, args.xteink_url, args.url, args.firmware, args.model)
        elif command == 'library': bridge.library(args.books, args.port)
        elif command == 'progress': bridge.progress()
        elif command == 'import-clippings': bridge.import_clippings(args.path)
        elif command == 'uninstall': bridge.uninstall()
    except (SetupError, OSError, ValueError, KeyError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
        # Only our own error messages are safe to display: JSON/HTTP failures may contain secrets.
        print(str(exc) if isinstance(exc, SetupError) else f'Setup paused ({type(exc).__name__}). Check inputs/connectivity and rerun; completed checkpoints are preserved.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nSetup paused; rerun to resume.', file=sys.stderr)
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
