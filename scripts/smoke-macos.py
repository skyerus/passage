#!/usr/bin/env python3
"""Exercise the bundled helper and a disposable launchd collector on macOS.

Run with the packaged interpreter: <app>/Contents/Resources/runtime/bin/python3
scripts/smoke-macos.py <app>. Uses random service labels, ports and temporary
fixtures; never pairs a real reader or accesses the user's archive.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid


def main():
    app = Path(sys.argv[1]).resolve()
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
            assert json.loads(export.read_text())[0]['title'] == 'Acceptance Fixture'
            assert upload('crosspoint', {'id': 'one', 'deleted': True})['accepted'] == ['one']
            assert invoke('status')['highlight_count'] == 0
            upload('koreader', sample)
            assert invoke('status')['highlight_count'] == 0
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
            sd = root / 'sd'
            (sd / '.crosspoint').mkdir(parents=True)
            invoke('pair_xteink', mount=str(sd), endpoint=endpoint, firmware=False, model_confirmed=True)
            assert json.loads((sd / '.crosspoint/highlight-sync.json').read_text())['token'] == token
            invoke('stop_collector')
            assert not invoke('status')['service']['healthy']
            assert not (agents / (labels['collector'] + '.plist')).exists()
            print('PASS: bundled runtime, launchd start/restart/stop, authenticated uploads, deduplication, full-archive search, export, deletion replay, and fixture pairing.')
        finally:
            for label in labels.values():
                subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{label}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
