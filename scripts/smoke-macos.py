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
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import uuid


def main():
    app = Path(sys.argv[1]).resolve()
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    bridge_source = app / 'Contents/Resources/bridge'
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
            for _ in range(40):
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
            for _ in range(40):
                receipt = json.loads((data / 'cloud_backup/receipt.json').read_text())
                if receipt.get('digest') != first_receipt['digest']:
                    break
                time.sleep(.25)
            assert receipt['digest'] != first_receipt['digest']
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
            queue = kindle / 'koreader/settings/sharedhighlights-queue.json'
            queue.write_text('{"fixture":"offline queue"}')
            invoke('pair_kindle', mount=str(kindle), endpoint=endpoint)
            assert queue.read_text() == '{"fixture":"offline queue"}'
            assert (kindle / 'koreader/plugins/sharedhighlights.koplugin/cover.lua').read_bytes() == (bridge_source / 'koreader/sharedhighlights.koplugin/cover.lua').read_bytes()
            sd = root / 'sd'
            (sd / '.crosspoint').mkdir(parents=True)
            invoke('pair_xteink', mount=str(sd), endpoint=endpoint, firmware=False, model_confirmed=True)
            assert json.loads((sd / '.crosspoint/highlight-sync.json').read_text())['token'] == token
            # The app provisions a private KOSync service independently of the
            # highlight collector, including for legacy collector installations.
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',0)); progress_port = sock.getsockname()[1]
            progress = invoke('start_progress',endpoint=endpoint,port=progress_port)['local_progress']
            assert progress['healthy'] and not progress['kindle_paired'] and progress['book_count'] == 0
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
            invoke('pair_progress_xteink',mount=str(sd))
            progress = invoke('status')['local_progress']
            assert progress['kindle_paired'] and progress['xteink_paired'] and not progress['verified']
            assert queue.read_text() == '{"fixture":"offline queue"}'
            assert json.loads((sd / '.crosspoint/highlight-sync.json').read_text())['token'] == token
            spec = __import__('plistlib').loads((agents / (labels['progress_sync']+'.plist')).read_bytes())
            assert spec['RunAtLoad'] and spec['KeepAlive']
            subprocess.run(['launchctl','kickstart','-k',f'gui/{os.getuid()}/{labels["progress_sync"]}'],check=True)
            for _ in range(40):
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
    main()
