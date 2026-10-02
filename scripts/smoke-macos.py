#!/usr/bin/env python3
"""Exercise the bundled helper and a disposable launchd collector on macOS.

Run with the packaged interpreter: <app>/Contents/Resources/runtime/bin/python3 -B
scripts/smoke-macos.py <app>. Uses random service labels, ports and temporary
fixtures; never pairs a real reader or accesses the user's archive.
"""
import sys

if not sys.dont_write_bytecode:
    raise SystemExit('Run the packaged interpreter with -B to preserve the app signature.')

import base64
import ctypes
import json
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import subprocess
import tempfile
import time
import uuid


def main():
    app = Path(sys.argv[1]).resolve()
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    bridge_source = app / 'Contents/Resources/bridge'
    assert Path(sys.executable).resolve().is_relative_to(app / 'Contents/Resources/runtime')
    assert ssl.OPENSSL_VERSION and ctypes.sizeof(ctypes.c_void_p) in (4, 8)
    native_database = sqlite3.connect(':memory:')
    try:
        assert native_database.execute('SELECT 1').fetchone() == (1,)
    finally:
        native_database.close()
    forbidden = {'git', 'gh', 'pip', 'pip3', 'pio', 'platformio', 'swift', 'swiftc', 'xcrun', 'xcodebuild', 'clang', 'make'}
    def reject_developer_process(event, args):
        if event == 'subprocess.Popen':
            executable = Path(args[0])
            if executable.name in forbidden or (executable.name.startswith('python') and executable.resolve() != Path(sys.executable).resolve()):
                raise RuntimeError('Basic packaged acceptance attempted to use a developer tool')
    sys.addaudithook(reject_developer_process)
    sys.path.insert(0, str(bridge_source))
    import desktop
    import setup
    labels = {kind: f'com.readerbridge.acceptance.{uuid.uuid4().hex}.{kind}' for kind in setup.LABELS}
    setup.LABELS.update(labels)
    with tempfile.TemporaryDirectory(prefix='reader-bridge-acceptance-') as temporary:
        root = Path(temporary).resolve()
        data = root / 'data'
        agents = root / 'agents'
        def invoke(command, **args):
            return desktop.execute({'command': command, **args}, data, agents)
        assert invoke('status')['highlight_count'] == 0 and not data.exists()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        try:
            status = invoke('start_collector', port=port)
            assert status['service']['healthy'] and status['service']['mode'] == 'local'
            assert status['service']['installed']
            token = (data / 'collector/data/token').read_text().strip()
            spec = __import__('plistlib').loads((agents / (labels['collector'] + '.plist')).read_bytes())
            assert spec['RunAtLoad'] and spec['KeepAlive']
            assert spec['ProgramArguments'][0] == sys.executable
            # The system helper is in the app; a host Python is never selected.
            assert Path(spec['ProgramArguments'][0]).resolve().is_relative_to(app / 'Contents/Resources/runtime')
            again = invoke('start_collector', port=port)
            assert again['service']['healthy']
            assert (data / 'collector/data/token').read_text().strip() == token
            with socket.socket() as occupied:
                occupied.bind(('0.0.0.0', 0))
                occupied.listen()
                try:
                    invoke('start_collector', port=occupied.getsockname()[1])
                    raise AssertionError('An unrelated occupied port was accepted')
                except setup.SetupError:
                    pass
            assert invoke('status')['service']['healthy']
            assert (data / 'collector/data/token').read_text().strip() == token
            sample = {'id': 'one', 'book_title': 'Acceptance Fixture', 'author': 'Reader Bridge', 'text': 'A test passage that belongs only to the temporary acceptance archive.'}
            def upload(source, record):
                body = json.dumps({'source': source, 'device_id': 'acceptance-' + source, 'highlights': [record]}).encode()
                return json.loads(setup.http(f'http://127.0.0.1:{port}/v1/highlights', body, headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}))
            assert upload('koreader', sample)['accepted'] == ['one']
            assert upload('crosspoint', sample)['accepted'] == ['one']
            assert invoke('status')['highlight_count'] == 1
            # First highlight from an unseen book, followed by the device's raw
            # artwork request: no desktop import or pre-existing catalog entry.
            from urllib.parse import quote
            image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=')
            acknowledgement = json.loads(setup.http(f'http://127.0.0.1:{port}/v1/covers', image,
                headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'image/png',
                         'X-Book-Title': quote(sample['book_title']), 'X-Book-Author': quote(sample['author'])}))
            assert acknowledgement['status'] == 'stored'
            cover_path = Path(invoke('status')['books'][0]['cover_path'])
            assert cover_path.read_bytes() == image
            assert invoke('status', query='temporary acceptance')['highlights_matches'] == 1
            # Relaunch through launchd, then verify both the token and inbox survive.
            subprocess.run(['launchctl', 'kickstart', '-k', f'gui/{os.getuid()}/{labels["collector"]}'], check=True)
            for _ in range(120):
                if invoke('status')['service']['healthy']:
                    break
                time.sleep(.25)
            assert invoke('status')['service']['healthy']
            assert invoke('status')['highlight_count'] == 1
            assert (data / 'collector/data/token').read_text().strip() == token
            export = root / 'quotes.json'
            assert invoke('export', path=str(export))['exported'] == 1
            exported = json.loads(export.read_text())['highlights'][0]
            assert exported['title'] == 'Acceptance Fixture'
            assert base64.b64decode(exported['cover_image']) == image
            backup_folder = root / 'backup-folder'
            backup_folder.mkdir()
            backed_up = invoke('configure_cloud_backup', provider='folder', folder=str(backup_folder))
            assert backed_up['cloud_backup']['enabled'] and backed_up['cloud_backup']['saved_at']
            assert not backed_up['cloud_backup']['cloud_upload_verified']
            first_receipt = json.loads((data / 'cloud_backup/receipt.json').read_text())
            backup_spec = __import__('plistlib').loads((agents / (labels['cloud_backup'] + '.plist')).read_bytes())
            assert backup_spec['RunAtLoad'] and backup_spec['KeepAlive']
            assert upload('crosspoint', {'id': 'one', 'deleted': True})['accepted'] == ['one']
            assert invoke('status')['highlight_count'] == 0
            upload('koreader', sample)
            assert invoke('status')['highlight_count'] == 0
            subprocess.run(['launchctl', 'kickstart', '-k', f'gui/{os.getuid()}/{labels["cloud_backup"]}'], check=True)
            for _ in range(120):
                receipt = json.loads((data / 'cloud_backup/receipt.json').read_text())
                if receipt.get('digest') != first_receipt['digest']:
                    break
                time.sleep(.25)
            assert receipt['digest'] != first_receipt['digest'], 'Restarted backup worker did not save a changed archive within 30 seconds'
            assert Path(first_receipt['path']).is_file()
            invoke('restore_backup', path=first_receipt['path'])
            assert invoke('status')['highlight_count'] == 0, 'Old backups must not resurrect deleted quotes'
            invoke('disable_cloud_backup')
            assert not invoke('status')['cloud_backup']['enabled']
            assert not (agents / (labels['cloud_backup'] + '.plist')).exists()
            assert Path(receipt['path']).is_file()
            # Pair only disposable volumes; verify an offline queue is retained.
            verifier = desktop.Desktop(data, agent_dir=agents)
            endpoint = next((url for url in status['addresses'] if verifier.authenticated(port, url)), None)
            assert endpoint, 'No discovered LAN endpoint can reach the collector; check local network permission'
            kindle = root / 'kindle'
            (kindle / 'koreader/settings').mkdir(parents=True)
            (kindle / 'koreader/reader.lua').write_text('-- fixture\n')
            (kindle / 'koreader/settings.reader.lua').write_text('return {device_id="fixture-kindle"}\n')
            (kindle / 'koreader/frontend').mkdir()
            (kindle / 'koreader/frontend/userpatch.lua').write_text('-- registerPatchPluginFunc fixture\n')
            (kindle / 'koreader/plugins/kosync.koplugin').mkdir(parents=True)
            (kindle / 'koreader/plugins/kosync.koplugin/main.lua').write_text('\n'.join('function KOSync:'+name+'() end' for name in ('getMetadata','updateProgress','getProgress','syncToProgress','_onCloseDocument','_onNetworkConnected')))
            queue = kindle / 'koreader/settings/sharedhighlights-queue.json'
            queue.write_text('{"fixture":"offline queue"}')
            invoke('pair_kindle', mount=str(kindle), endpoint=endpoint)
            assert queue.read_text() == '{"fixture":"offline queue"}'
            assert (kindle / 'koreader/plugins/sharedhighlights.koplugin/cover.lua').read_bytes() == (bridge_source / 'koreader/sharedhighlights.koplugin/cover.lua').read_bytes()
            # Exercise every actual bundled image through the desktop command,
            # with developer tools unavailable and only disposable SD volumes.
            # Source-only CI builds have no images; report that scope explicitly.
            import device_profiles
            staged_models = []
            for model, profile in device_profiles.registry().items():
                artifact = profile.get('prebuilt') or {}
                if not artifact.get('bundled_path'):
                    continue
                volume = root / 'firmware-fixtures' / model
                (volume / '.crosspoint').mkdir(parents=True)
                staged = invoke('pair_xteink', mount=str(volume), endpoint=endpoint,
                                firmware=True, model_confirmed=True, model=model)
                assert staged['xteink']['model'] == model and staged['xteink']['firmware_staged']
                assert (volume / profile['filename']).read_bytes() == (bridge_source / artifact['bundled_path']).read_bytes()
                assert json.loads((volume / '.crosspoint/passage-device.json').read_text())['model'] == model
                assert json.loads((volume / '.crosspoint/highlight-sync.json').read_text())['token'] == token
                staged_models.append(model)
            print('Bundled firmware staged on disposable volumes: ' + (', '.join(staged_models) or 'none in this build'))
            sd = root / 'sd'
            (sd / '.crosspoint').mkdir(parents=True)
            invoke('pair_xteink', mount=str(sd), endpoint=endpoint, firmware=False, model_confirmed=True, model='xteink_x4_pro')
            assert json.loads((sd / '.crosspoint/highlight-sync.json').read_text())['token'] == token
            # The app provisions a private KOSync service independently of the
            # highlight collector, including for legacy collector installations.
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); progress_port = sock.getsockname()[1]
            progress = invoke('start_progress',endpoint=endpoint,port=progress_port)['local_progress']
            assert progress['healthy'] and not progress['kindle_paired'] and progress['book_count'] == 0
            # Upgrade a real owned listener with the pre-guard health contract.
            installed_service=data/'progress_sync/progress_sync.py'
            installed_service.write_text(installed_service.read_text().replace(", 'revision_guard':1",''))
            subprocess.run(['launchctl','kickstart','-k',f'gui/{os.getuid()}/{labels["progress_sync"]}'],check=True)
            probe=desktop.Desktop(data,agent_dir=agents)
            for _ in range(120):
                if probe.progress_authenticated(require_guard=False) and not probe.progress_authenticated():break
                time.sleep(.25)
            assert probe.progress_authenticated(require_guard=False) and not probe.progress_authenticated()
            assert invoke('start_progress',endpoint=endpoint,port=progress_port)['local_progress']['healthy']
            import progress_sync
            credentials = progress_sync.credentials(data / 'progress_sync')
            headers = {**progress_sync.auth_headers(credentials),'Content-Type':'application/json'}
            position = {'document':'a'*32,'progress':'/body/DocFragment[3]/body/p[1].0','percentage':.4,'device':'Kindle','device_id':'fixture-kindle'}
            base = f'http://127.0.0.1:{progress_port}'
            setup.http(base+'/syncs/progress',json.dumps(position).encode(),method='PUT',headers=headers)
            pulled = json.loads(setup.http(base+'/syncs/progress/'+'a'*32,headers=headers))
            assert pulled['progress'] == position['progress']
            position.update(percentage=.2,progress='/body/DocFragment[2]/body/p[1].0',device='CrossPoint',device_id='crosspoint-reader')
            setup.http(base+'/syncs/progress',json.dumps(position).encode(),method='PUT',headers=headers)
            assert json.loads(setup.http(base+'/syncs/progress/'+'a'*32,headers=headers))['percentage'] == .2
            invoke('pair_progress_kindle',mount=str(kindle))
            invoke('pair_progress_xteink',mount=str(sd),model='xteink_x4_pro')
            progress = invoke('status')['local_progress']
            assert progress['kindle_paired'] and progress['xteink_paired'] and not progress['verified']
            # Real HTTP replay against the installed, paired background service.
            from urllib.error import HTTPError
            stale = dict(position, progress='stale-kindle-position', device='Kindle', device_id='fixture-kindle',
                         metadata={'reader_bridge':{'version':1,'base_revision':pulled['reader_bridge_revision']}})
            try:
                setup.http(base+'/syncs/progress',json.dumps(stale).encode(),method='PUT',headers=headers)
                raise AssertionError('Stale paired upload was accepted')
            except HTTPError as exc:
                assert exc.code == 409
            retained=json.loads(setup.http(base+'/syncs/progress/'+'a'*32,headers=headers))
            assert retained['percentage'] == .2 and retained['device'] == 'CrossPoint'
            assert (kindle/'koreader/patches/2-reader-bridge-progress.lua').read_bytes() == (bridge_source/'koreader/patches/2-reader-bridge-progress.lua').read_bytes()
            assert queue.read_text() == '{"fixture":"offline queue"}'
            assert json.loads((sd / '.crosspoint/highlight-sync.json').read_text())['token'] == token
            spec = __import__('plistlib').loads((agents / (labels['progress_sync']+'.plist')).read_bytes())
            assert spec['RunAtLoad'] and spec['KeepAlive']
            subprocess.run(['launchctl','kickstart','-k',f'gui/{os.getuid()}/{labels["progress_sync"]}'],check=True)
            for _ in range(120):
                if invoke('status')['local_progress']['healthy']: break
                time.sleep(.25)
            assert invoke('status')['local_progress']['healthy']
            assert progress_sync.credentials(data/'progress_sync') == credentials
            assert json.loads(setup.http(base+'/syncs/progress/'+'a'*32,headers=headers))['percentage'] == .2
            backed_up = invoke('configure_cloud_backup',provider='folder',folder=str(backup_folder))
            import archive_backup
            manifest,_ = archive_backup.read_snapshot(backed_up['cloud_backup']['snapshot_path'])
            assert manifest['version'] == 2 and manifest['positions'][0]['percentage'] == .2
            assert credentials['password'] not in json.dumps(manifest)
            invoke('disable_cloud_backup')
            invoke('stop_progress')
            assert not invoke('status')['local_progress']['healthy']
            assert not (agents / (labels['progress_sync']+'.plist')).exists()
            assert (data/'progress_sync/positions.sqlite3').is_file()
            invoke('stop_collector')
            assert not invoke('status')['service']['healthy']
            assert not (agents / (labels['collector'] + '.plist')).exists()
            print('PASS: bundled runtime, launchd recovery, uploads and original cover bytes, search, export, automatic folder backup, backup-worker restart, safe restore, deletion replay, fixture pairing, local progress roundtrip, progress restart, and position backups.')
        finally:
            for label in labels.values():
                subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{label}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)


if __name__ == '__main__':
    fixture_home = os.environ.get('PASSAGE_ACCEPTANCE_HOME')
    if fixture_home:
        # Test-only lookup substitution. Never repurpose the user's HOME.
        from unittest.mock import patch
        fixture = Path(fixture_home).resolve()
        if not fixture.is_dir() or fixture.is_symlink():
            raise SystemExit('Invalid disposable acceptance home')
        with patch.object(Path, 'home', return_value=fixture):
            main()
    else:
        main()
