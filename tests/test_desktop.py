import contextlib
import io
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock

import collector
import desktop
import setup


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.app = self.root / 'app'
        self.agents = self.root / 'agents'
        self.bridge = desktop.Desktop(self.app, agent_dir=self.agents)

    def tearDown(self):
        self.temp.cleanup()

    def initialize(self):
        directory, token = collector.initialize(self.app / 'collector/data')
        self.store = collector.Store(directory / 'inbox.sqlite3')
        return token

    @contextlib.contextmanager
    def server(self):
        token = self.initialize()
        server = collector.server(self.store, token, '127.0.0.1', 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.bridge.state['collector'] = {'port': server.server_port}
        self.bridge.save()
        try:
            yield server.server_port, token
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def upload(self, port, token, source, device, rows):
        return json.loads(setup.http(f'http://127.0.0.1:{port}/v1/highlights', json.dumps({'source': source, 'device_id': device, 'highlights': rows}).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}))

    def item(self, ident='1', text='A private quote'):
        return {'id': ident, 'book_title': 'Book', 'author': 'Author', 'text': text, 'created_at': '2026-10-01'}

    def owned_agent(self, kind='collector'):
        path = self.bridge.agent_path(kind)
        args = [sys.executable, str(self.app / 'collector/collector.py')] if kind == 'collector' else [str(self.app / 'library/venv/bin/cps'), '-p', 'db']
        setup.atomic_write(path, plistlib.dumps({'Label': setup.LABELS[kind], 'WorkingDirectory': str(self.app / kind), 'ProgramArguments': args}))
        self.bridge.state.setdefault(kind, {})['agent'] = str(path)
        self.bridge.save()
        return path

    def test_status_uninitialized_is_read_only(self):
        with patch.object(desktop, 'Store', side_effect=AssertionError('must not initialize')), patch.object(setup, 'run', side_effect=AssertionError('must not run')):
            status = self.bridge.status()
        self.assertFalse(self.app.exists())
        self.assertFalse(self.agents.exists())
        self.assertEqual(status['highlight_count'], 0)
        self.assertEqual(status['service']['mode'], 'local')
        self.assertFalse(status['service']['installed'])
        self.assertFalse(status['service']['healthy'])
        self.assertNotIn('token', json.dumps(status))

    def test_http_dedup_delete_and_authenticate(self):
        with self.server() as (port, token):
            self.assertTrue(self.bridge.authenticated(port))
            self.assertEqual(self.store.pending(), [])
            self.upload(port, token, 'koreader', 'kindle', [self.item()])
            self.upload(port, token, 'crosspoint', 'xteink', [self.item('2')])
            state = self.bridge.status()
            self.assertEqual(state['highlight_count'], 1)
            self.assertEqual(state['highlights'][0]['text'], 'A private quote')
            self.assertEqual(state['service']['pending_backup'], 0)
            self.upload(port, token, 'koreader', 'kindle', [{'id': '1', 'deleted': True}])
            self.assertEqual(self.bridge.status()['highlight_count'], 0)
            self.upload(port, token, 'crosspoint', 'xteink', [self.item('3')])
            self.assertEqual(self.bridge.status()['highlight_count'], 0)
            setup.atomic_write(self.app / 'collector/data/token', b'x' * 43)
            self.assertFalse(self.bridge.authenticated(port))

    def test_read_only_listing_and_count_cap(self):
        self.initialize()
        for number in range(501):
            self.store.accept({'source': 'koreader', 'device_id': 'fixture', 'highlights': [self.item(str(number), str(number))]})
        path = self.app / 'collector/data/inbox.sqlite3'
        before = path.read_bytes(), path.stat().st_mtime_ns
        with patch.object(desktop, 'Store', side_effect=AssertionError('write')):
            status = self.bridge.status()
        self.assertEqual(status['highlight_count'], 501)
        self.assertEqual(len(status['highlights']), 500)
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        output = self.root / 'export.json'
        result = self.bridge.mutate('export', {'path': str(output)})
        self.assertEqual(result['exported'], 501)
        self.assertEqual(len(json.loads(output.read_text())), 501)
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(setup.SetupError):
            self.bridge.mutate('export', {'path': str(output)})
        with self.assertRaises(setup.SetupError):
            self.bridge.mutate('export', {'path': str(self.app / 'state.json')})

    def test_local_start_has_no_github_and_preserves_inbox_token(self):
        token = self.initialize()
        self.store.accept({'source': 'koreader', 'device_id': 'fixture', 'highlights': [self.item()]})
        with patch.object(desktop.sys, 'platform', 'darwin'), patch.object(self.bridge, 'gh', side_effect=AssertionError('GitHub')), patch.object(self.bridge, 'check_port'), patch.object(self.bridge, 'launch') as launch, patch.object(self.bridge, 'authenticated', return_value=True):
            self.bridge.start_local(8084)
            self.bridge.start_local(8084)
        self.assertEqual((self.app / 'collector/data/token').read_text().strip(), token)
        self.assertEqual(self.bridge.status()['highlight_count'], 1)
        args = launch.call_args.args[1]
        self.assertEqual(args[0], sys.executable)
        self.assertIn('--no-publish', args)
        self.assertNotIn('--repo', args)

    @patch.object(desktop.sys, 'platform', 'darwin')
    def test_start_preserves_backup_and_disable_preserves_rows(self):
        self.initialize()
        self.store.accept({'source': 'koreader', 'device_id': 'fixture', 'highlights': [self.item()]})
        self.bridge.state['collector'] = {'archive': 'reader/private', 'branch': 'main', 'port': 8084}
        with patch.object(self.bridge, 'check_port'), patch.object(self.bridge, 'collector') as backup:
            self.bridge.start_local(8084)
            backup.assert_called_once_with('reader/private', port=8084)
        with patch.object(self.bridge, 'check_port'), patch.object(self.bridge, 'launch'), patch.object(self.bridge, 'authenticated', return_value=True):
            self.bridge.start_local(8084, disable=True)
            self.assertEqual(self.bridge.status()['service']['mode'], 'local')
            self.assertEqual(self.bridge.status()['service']['pending_backup'], 0)
            self.assertEqual(self.bridge.status()['highlight_count'], 1)
            with patch.object(self.bridge, 'collector') as backup:
                self.bridge.start_local(8084)
                backup.assert_not_called()

    def test_pairing_preserves_kindle_and_xteink_queues(self):
        self.initialize()
        kindle = self.root / 'kindle'
        setup.atomic_write(kindle / 'koreader/reader.lua', b'fixture')
        queue = kindle / 'koreader/settings/sharedhighlights-queue.json'
        setup.atomic_write(queue, b'{"pending":"private"}')
        card = self.root / 'sd'
        setup.atomic_write(card / '.crosspoint/queue.json', b'private')
        with patch.object(self.bridge, 'authenticated', return_value=True), contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2):
                self.bridge.mutate('pair_kindle', {'mount': str(kindle), 'endpoint': 'http://mac.local:8084'})
                self.bridge.mutate('pair_xteink', {'mount': str(card), 'endpoint': 'http://mac.local:8084', 'model_confirmed': True, 'firmware': False})
        self.assertEqual(queue.read_bytes(), b'{"pending":"private"}')
        self.assertEqual((card / '.crosspoint/queue.json').read_bytes(), b'private')
        with patch.object(self.bridge, 'xteink') as pair:
            with self.assertRaises(setup.SetupError):
                self.bridge.mutate('pair_xteink', {'mount': str(card)})
            pair.assert_not_called()

    def test_invalid_arguments_and_port_collision(self):
        for value in (True, '8084', 0, 1023, 65536, None):
            with self.assertRaises(setup.SetupError):
                desktop.port_arg(value)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            with self.assertRaises(setup.SetupError):
                self.bridge.check_port('collector', sock.getsockname()[1])
        for body in ([], {}, {'command': 'other'}, {'command': 3}):
            with self.assertRaises(setup.SetupError):
                desktop.execute(body, self.app, self.agents)
        self.assertFalse(self.app.exists())

    def test_ownership_checks_prevent_stopping_unrelated_agent(self):
        path = self.owned_agent()
        spec = plistlib.loads(path.read_bytes())
        spec['WorkingDirectory'] = '/somewhere/else'
        setup.atomic_write(path, plistlib.dumps(spec))
        with patch.object(desktop.subprocess, 'run', side_effect=AssertionError('must not stop')):
            with self.assertRaises(setup.SetupError):
                self.bridge.mutate('stop_collector', {})
        self.assertTrue(path.exists())

    def test_loaded_unowned_agent_cannot_be_replaced(self):
        with patch.object(desktop.subprocess, 'run', return_value=Mock(returncode=0)), patch.object(setup.Bridge, 'launch', side_effect=AssertionError('must not launch')):
            with self.assertRaises(setup.SetupError):
                self.bridge.launch('collector', [sys.executable, 'collector.py'], self.app / 'collector')

    def test_loaded_identity_must_match_owned_plist_before_bootout(self):
        path = self.owned_agent()
        good = f'path = {path}\nprogram = {sys.executable}\nworking directory = {self.app / "collector"}\n'
        for response in (good.replace(str(path), '/different/job.plist'), good.replace(sys.executable, '/different/executable'), good.replace(str(self.app / 'collector'), '/different/directory')):
            with patch.object(desktop.sys, 'platform', 'darwin'), patch.object(desktop.subprocess, 'run', return_value=Mock(returncode=0, stdout=response)) as run:
                with self.assertRaises(setup.SetupError):
                    self.bridge.mutate('stop_collector', {})
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0][1], 'print')
                self.assertTrue(path.exists())
        with patch.object(desktop.subprocess, 'run', return_value=Mock(returncode=0, stdout=good)):
            self.bridge.assert_loaded_ownership('collector')

    def test_lock_prevents_lost_update_and_reloads_state(self):
        with desktop.mutation_lock(self.app):
            with self.assertRaises(setup.SetupError):
                desktop.execute({'command': 'verify_progress', 'verified': True}, self.app, self.agents)
        desktop.execute({'command': 'verify_progress', 'verified': True}, self.app, self.agents)
        self.assertTrue(desktop.execute({'command': 'status'}, self.app, self.agents)['progress_verified'])

    def test_protocol_one_json_and_safe_error(self):
        command = [sys.executable, '-B', str(Path(desktop.__file__)), '--app-dir', str(self.app)]
        status = subprocess.run(command, input='{"command":"status"}', text=True, capture_output=True, check=True)
        self.assertTrue(json.loads(status.stdout)['ok'])
        self.assertEqual(status.stderr, '')
        self.assertFalse(self.app.exists())
        bad = subprocess.run(command, input='{"secret":"private quote"', text=True, capture_output=True, check=True)
        self.assertFalse(json.loads(bad.stdout)['ok'])
        self.assertNotIn('private quote', bad.stdout + bad.stderr)
        oversized = subprocess.run(command, input='x' * (desktop.MAX_REQUEST + 1), text=True, capture_output=True, check=True)
        self.assertFalse(json.loads(oversized.stdout)['ok'])

    def test_clippings_import_real_http_and_repeat(self):
        with self.server():
            path = self.root / 'My Clippings.txt'
            data = 'Book (Author)\n- Your Highlight on Location 1-2\n\nImported passage\n==========\n'
            path.write_text(data)
            first = self.bridge.mutate('import_clippings', {'path': str(path)})
            second = self.bridge.mutate('import_clippings', {'path': str(path)})
            self.assertEqual(first['highlight_count'], 1)
            self.assertEqual(second['highlight_count'], 1)
            self.assertEqual(path.read_text(), data)
            self.assertEqual(first['highlights'][0]['text'], 'Imported passage')

    def test_configure_backup_keeps_local_inbox(self):
        import base64
        token = self.initialize()
        self.bridge.state['collector'] = {'port': 8084, 'backup_disabled': True}
        self.bridge.save()
        self.store.accept({'source': 'koreader', 'device_id': 'fixture', 'highlights': [self.item()]})
        responses = ['', json.dumps({'isPrivate': True, 'defaultBranchRef': {'name': 'main'}}), json.dumps({'content': base64.b64encode(b'[]').decode()})]
        with patch.object(desktop.sys, 'platform', 'darwin'), patch.object(self.bridge, 'gh', side_effect=responses), patch.object(self.bridge, 'check_port'), patch.object(setup, 'run', return_value=''), patch.object(self.bridge, 'launch') as launch, patch.object(self.bridge, 'wait_health'), patch.object(self.bridge, 'authenticated', return_value=True), contextlib.redirect_stdout(io.StringIO()):
            result = self.bridge.mutate('configure_backup', {'archive': 'reader/private', 'create': False})
        self.assertEqual(result['service']['mode'], 'github')
        self.assertEqual(result['highlight_count'], 1)
        self.assertEqual(result['service']['pending_backup'], 1)
        self.assertEqual((self.app / 'collector/data/token').read_text().strip(), token)
        self.assertIn('--repo', launch.call_args.args[1])

    def test_launch_environment_disables_bytecode(self):
        with patch.object(desktop.sys, 'platform', 'darwin'), patch.object(desktop.subprocess, 'run', return_value=Mock(returncode=1)), patch.object(setup, 'run', return_value=''):
            self.bridge.launch('collector', [sys.executable, self.app / 'collector/collector.py', 'serve'], self.app / 'collector')
        spec = plistlib.loads(self.bridge.agent_path('collector').read_bytes())
        self.assertEqual(spec['EnvironmentVariables']['PYTHONDONTWRITEBYTECODE'], '1')

    def test_library_port_requires_loaded_pid_socket_match(self):
        self.bridge.state['library'] = {'port': 8083}
        path = self.owned_agent('library')
        loaded = Mock(returncode=0, stdout=f'path = {path}\n pid = 4242\n')
        listener = Mock(returncode=0, stdout='p4242\n')
        with patch.object(desktop.sys, 'platform', 'darwin'), patch.object(setup, 'available', return_value=False), patch.object(desktop.subprocess, 'run', side_effect=[loaded, listener]):
            self.bridge.check_port('library', 8083)
        wrong = Mock(returncode=0, stdout='p9999\n')
        with patch.object(desktop.sys, 'platform', 'darwin'), patch.object(setup, 'available', return_value=False), patch.object(desktop.subprocess, 'run', side_effect=[loaded, wrong]):
            with self.assertRaises(setup.SetupError):
                self.bridge.check_port('library', 8083)

    def test_port_change_preserves_host_and_refuses_paired_readers(self):
        self.bridge.state = {'collector': {'port': 8084}, 'url': 'http://mac.local:8084'}
        with patch.object(desktop.sys, 'platform', 'darwin'), patch.object(self.bridge, 'check_port'), patch.object(self.bridge, 'launch'), patch.object(self.bridge, 'authenticated', return_value=True):
            self.bridge.start_local(8085)
        self.assertEqual(self.bridge.state['url'], 'http://mac.local:8085')
        self.bridge.state['kindle'] = {'installed': True}
        with patch.object(self.bridge, 'check_port', side_effect=AssertionError('must reject before touching services')):
            with self.assertRaises(setup.SetupError):
                self.bridge.start_local(8086)

    def test_search_before_cap_and_total_count(self):
        self.initialize()
        for number in range(501):
            self.store.accept({'source': 'koreader', 'device_id': 'fixture', 'highlights': [self.item(str(number), f'Passage {number}') ]})
        status = desktop.execute({'command': 'status', 'query': 'Passage 500'}, self.app, self.agents)
        self.assertEqual(status['highlight_count'], 501)
        self.assertEqual(status['highlights_matches'], 1)
        self.assertEqual(status['highlights'][0]['text'], 'Passage 500')
        with self.assertRaises(setup.SetupError):
            desktop.execute({'command': 'status', 'query': 'x' * 1001}, self.app, self.agents)

    def test_dmg_service_install_blocked(self):
        with patch.object(setup, 'SOURCE', Path('/Volumes/Reader Bridge/Reader Bridge.app/Contents/Resources/backend')):
            with self.assertRaises(setup.SetupError):
                self.bridge.start_local(8084)
        self.assertFalse(self.app.exists())


if __name__ == '__main__':
    unittest.main()
