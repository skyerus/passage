import contextlib
import hashlib
import io
import itertools
import json
from pathlib import Path
import plistlib
import tempfile
import subprocess
import unittest
from unittest.mock import patch
import setup
from import_clippings import parse_clippings


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # On macOS /tmp aliases /private/tmp; resolve only our disposable fixture.
        self.root = Path(self.temp.name).resolve()
        self.bridge = setup.Bridge(self.root / 'app', agent_dir=self.root / 'agents')
    def tearDown(self):
        self.temp.cleanup()
    def token(self):
        setup.atomic_write(self.bridge.app / 'collector/data/token', b'x' * 43)
    def mount(self):
        mount = self.root / 'kindle'
        setup.atomic_write(mount / 'koreader/reader.lua', b'fixture')
        return mount
    def test_dry_run_has_no_writes_or_commands(self):
        bridge = setup.Bridge(self.root / 'missing', dry_run=True)
        with patch.object(setup, 'run', side_effect=AssertionError('command')), contextlib.redirect_stdout(io.StringIO()):
            setup.wizard(bridge)
            bridge.collector('example/personal', create=True)
            bridge.uninstall()
        self.assertFalse(bridge.app.exists())
    def test_private_url_gate(self):
        for url in ('http://192.168.1.9:8084', 'http://10.2.3.4', 'http://reader-mac.local:8084'):
            self.assertEqual(setup.private_url(url), url)
        for url in ('http://example.com', 'http://8.8.8.8', 'http://127.0.0.1', 'http://mac.local/path', 'http://user:pw@mac.local', 'http://mac.local?x=y', 'https://mac.local', 'http://mac.local:0', 'http://192.168.256.1'):
            with self.assertRaises(setup.SetupError): setup.private_url(url)
    def test_symlink_destination_refused(self):
        target = self.root / 'target'; target.mkdir()
        link = self.root / 'link'; link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(setup.SetupError): setup.atomic_write(link / 'token', b'secret')
        self.assertFalse((target / 'token').exists())
    def test_pairing_install_preserves_id_queue_and_backups(self):
        self.token(); mount = self.mount()
        settings = mount / 'koreader/settings'
        config = settings / 'sharedhighlights-config.json'
        queue = settings / 'sharedhighlights-queue.json'
        setup.atomic_write(config, json.dumps({'device_id': 'stable-id', 'url': 'http://old.local', 'token': 'oldsecret', 'extra': 'preserved'}).encode())
        setup.atomic_write(queue, b'{"pending":{"id":"offline quote"}}')
        before = queue.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.bridge.kindle(mount, 'http://mac.local:8084')
            self.bridge.kindle(mount, 'http://mac.local:8084')
        result = json.loads(config.read_text())
        self.assertEqual(result['device_id'], 'stable-id')
        self.assertEqual(result['extra'], 'preserved')
        self.assertEqual(queue.read_bytes(), before)
        self.assertEqual(result['token'], 'x' * 43)
        self.assertNotIn('x' * 43, output.getvalue())
        self.assertEqual(config.stat().st_mode & 0o777, 0o600)
        backups = list((self.bridge.app / 'backups').glob('*'))
        self.assertEqual(len(backups), 1)
        self.assertIn(b'oldsecret', backups[0].read_bytes())
    def test_xteink_sd_pairing_idempotent_and_model_gate(self):
        self.token(); mount = self.root / 'sd'; (mount / '.crosspoint').mkdir(parents=True)
        with self.assertRaises(setup.SetupError): self.bridge.xteink(mount=mount, model='x4')
        with contextlib.redirect_stdout(io.StringIO()):
            self.bridge.xteink(mount=mount, url='http://mac.local:8084', model='xteink_x4_pro')
            first = (mount / '.crosspoint/highlight-sync.json').read_bytes()
            self.bridge.xteink(mount=mount, url='http://mac.local:8084', model='xteink_x4_pro')
        self.assertEqual((mount / '.crosspoint/highlight-sync.json').read_bytes(), first)
        self.assertEqual(json.loads(first)['endpoint'], 'http://mac.local:8084/v1/highlights')
    def test_xteink_http_requires_model_before_pairing(self):
        self.token()
        with patch.object(setup, 'http', return_value=b'{"device":"X4"}') as http:
            with self.assertRaises(setup.SetupError): self.bridge.xteink(device_url='http://192.168.1.4', url='http://mac.local:8084', model='xteink_x4_pro')
        self.assertEqual(http.call_count, 1)
        self.assertNotIn('devices', self.bridge.state)
    def test_xteink_upload_readback_and_backup(self):
        client = setup.Xteink('http://192.168.1.4', self.bridge)
        with patch.object(setup, 'http', side_effect=[b'ok', b'ok', b'new']) as http:
            client.put_file('/.crosspoint/highlight-sync.json', b'new', b'old')
        self.assertIn('/delete?path=', http.call_args_list[0].args[0])
        self.assertIn('/upload?path=', http.call_args_list[1].args[0])
        self.assertEqual(len(list((self.bridge.app / 'backups').glob('*'))), 1)
        with patch.object(setup, 'http', side_effect=[b'ok', b'corrupt']):
            with self.assertRaises(setup.SetupError): client.put_file('/file.bin', b'new', None)
    def test_archive_repoint_and_public_defaults_refused(self):
        self.bridge.state['collector'] = {'archive': 'example/old'}
        with self.assertRaises(setup.SetupError): self.bridge.collector('example/new')
        for archive in ('skyerus/kindle-highlights', 'skyerus/reader-bridge', 'skyerus/passage', ''):
            with self.assertRaises(setup.SetupError): self.bridge.collector(archive)
    def test_port_conflict_does_not_modify_anything(self):
        with patch.object(setup, 'available', return_value=False):
            with self.assertRaises(setup.SetupError): self.bridge.collector('example/archive')
        self.assertFalse(self.bridge.app.exists())
    def test_uninstall_only_owned_agents(self):
        unrelated = self.bridge.agent_dir / 'com.someone.collector.plist'
        setup.atomic_write(unrelated, b'unrelated')
        agent = self.bridge.agent_path('collector'); setup.atomic_write(agent, b'owned')
        self.bridge.state['collector'] = {'agent': str(agent)}
        self.token()
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup.subprocess, 'run'), contextlib.redirect_stdout(io.StringIO()):
            self.bridge.uninstall()
        self.assertTrue(unrelated.exists()); self.assertFalse(agent.exists())
        self.assertTrue((self.bridge.app / 'collector/data/token').exists())
    def test_launch_failure_resumes_owned_plist(self):
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup, 'run', side_effect=setup.SetupError('lint failed')), \
                patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 113, stdout='', stderr='')):
            with self.assertRaises(setup.SetupError):
                self.bridge.launch('collector', ['/usr/bin/python3', 'collector.py'], self.bridge.app)
        resumed = setup.Bridge(self.bridge.app, agent_dir=self.bridge.agent_dir)
        self.assertEqual(resumed.state['collector']['agent'], str(resumed.agent_path('collector')))
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup, 'run', return_value=''), \
                patch.object(setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 113, stdout='', stderr='')):
            resumed.launch('collector', ['/usr/bin/python3', 'collector.py'], self.bridge.app)
        self.assertTrue(resumed.agent_path('collector').exists())

    def test_launch_refuses_unowned_plist(self):
        agent = self.bridge.agent_path('collector')
        setup.atomic_write(agent, b'not ours')
        with patch.object(setup.sys, 'platform', 'darwin'):
            with self.assertRaises(setup.SetupError): self.bridge.launch('collector', ['python3'], self.bridge.app)
        self.assertEqual(agent.read_bytes(), b'not ours')

    def test_import_clippings_filters_notes_deduplicates_preserves_text(self):
        entry = 'Book (Author)\n- Your Highlight on Location 1-2 | Added on Monday\n\nFirst line\nSecond line\n==========\n'
        rows = parse_clippings(entry + entry + 'Book (Author)\n- Your Note on Location 1\n\nPrivate note\n==========')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['text'], 'First line\nSecond line')
        self.assertEqual(rows[0]['book_title'], 'Book')
    def test_corrupt_state_error_has_no_traceback_or_secret(self):
        setup.atomic_write(self.bridge.state_path, b'PRIVATE-INVALID-STATE')
        with contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(setup.main(['--app-dir', str(self.bridge.app), 'status']), 1)
        self.assertNotIn('PRIVATE', output.getvalue()); self.assertNotIn('Traceback', output.getvalue())
    def test_large_unicode_import_stays_below_request_limit(self):
        self.token()
        self.bridge.state['collector'] = {'port': 8084}
        export = self.root / 'clippings.txt'
        export.write_text(''.join('Book (Author)\n- Your Highlight on Location %d\n\n%s\n==========\n' %
                                 (i, '\u0800' * 21840) for i in range(8)), encoding='utf-8')
        def receipt(url, payload, **kwargs):
            self.assertLess(len(payload), 1024 * 1024)
            records = json.loads(payload)['highlights']
            return json.dumps({'accepted': [item['id'] for item in records]}).encode()
        with patch.object(setup, 'http', side_effect=receipt), contextlib.redirect_stdout(io.StringIO()):
            self.bridge.import_clippings(export)
    def test_library_partial_bootstrap_preserves_secret_without_exposing_server(self):
        books = self.root / 'books'; setup.atomic_write(books / 'metadata.db', b'fixture')
        setup.atomic_write(self.bridge.app / 'library/venv/bin/python', b'fixture')
        def failing(command, **kwargs):
            if '-c' in command:
                self.assertIn('-g', command[command.index('-c') + 1])
                self.assertIn('-o', command[command.index('-c') + 1])
                self.assertNotIn(kwargs['input'], ' '.join(str(x) for x in command))
                raise setup.SetupError('bootstrap interrupted')
            return ''
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup, 'available', return_value=True), patch.object(setup, 'run', side_effect=failing), patch.object(self.bridge, 'launch') as launch:
            with self.assertRaises(setup.SetupError): self.bridge.library(books)
            credentials = (self.bridge.app / 'library/admin.json').read_bytes()
            with self.assertRaises(setup.SetupError): self.bridge.library(books)
            self.assertEqual((self.bridge.app / 'library/admin.json').read_bytes(), credentials)
            launch.assert_not_called()
        self.assertFalse((self.bridge.app / 'library/configured.json').exists())
        self.assertEqual((self.bridge.app / 'library/admin.json').stat().st_mode & 0o777, 0o600)

    def test_source_manifest_build_rejects_override(self):
        spec = json.loads((setup.SOURCE / 'firmware.json').read_text())['devices']['xteink_x4_pro']
        directory = self.bridge.app / 'builds' / spec['commit'] / spec['environment']
        source = directory / 'source'; source.mkdir(parents=True)
        setup.atomic_write(source / 'platformio.local.ini', b'[env:x4pro]\nextra_scripts=untrusted.py')
        setup.atomic_write(directory / 'venv/bin/python', b'fixture')
        with patch.object(setup, 'run', side_effect=['', spec['commit'] + '\n']), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(setup.SetupError): self.bridge.build_firmware(spec)


class LaunchLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.bridge = setup.Bridge(self.root / 'app', agent_dir=self.root / 'agents')
        self.kind = 'progress_sync'
        self.agent = self.bridge.agent_path(self.kind)
        self.directory = self.bridge.app / self.kind
        spec = {'Label': setup.LABELS[self.kind], 'ProgramArguments': ['/fixture/old-python', 'progress_sync.py'],
                'WorkingDirectory': str(self.directory)}
        setup.atomic_write(self.agent, plistlib.dumps(spec))
        self.bridge.state[self.kind] = {'agent': str(self.agent)}
        self.identity = f'path = {self.agent}\nprogram = /fixture/old-python\nworking directory = {self.directory}\n'
        self.statuses = []
        self.events = []
        self.removal_code = 0
        self.bootstrap_error = False

    def loaded(self, identity=None):
        return subprocess.CompletedProcess([], 0, stdout=identity or self.identity, stderr='')

    def absent(self):
        return subprocess.CompletedProcess([], 113, stdout='', stderr='Could not find service fixture')

    def subprocess(self, command, **kwargs):
        self.events.append(command[1])
        if command[1] == 'print':
            return self.statuses.pop(0) if self.statuses else self.loaded()
        self.assertEqual(command[1], 'bootout')
        return subprocess.CompletedProcess(command, self.removal_code, stdout='', stderr='')

    def setup_command(self, command, **kwargs):
        operation = command[1]
        self.events.append(operation)
        if operation == 'bootstrap' and self.bootstrap_error:
            raise setup.SetupError('bootstrap fixture failure')
        return ''

    def launch(self):
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup, 'run', side_effect=self.setup_command), \
                patch.object(setup.subprocess, 'run', side_effect=self.subprocess), patch.object(setup.time, 'sleep'):
            self.bridge.launch(self.kind, ['/fixture/new-python', 'progress_sync.py'], self.directory)

    def test_replacement_waits_for_owned_old_identity_to_disappear(self):
        self.statuses = [self.loaded(), self.loaded(), self.loaded(), self.loaded(), self.absent()]
        self.launch()
        self.assertEqual(self.events, ['print', '-lint', 'print', 'bootout', 'print', 'print', 'print', 'bootstrap'])
        self.assertFalse(self.statuses)

    def test_owned_removal_wait_is_bounded_without_bootstrap_retry(self):
        original = self.agent.read_bytes()
        with patch.object(setup.time, 'monotonic', side_effect=itertools.count()):
            with self.assertRaisesRegex(setup.SetupError, 'still in progress'):
                self.launch()
        self.assertEqual(self.events.count('bootout'), 1)
        self.assertLessEqual(self.events.count('print'), 8)
        self.assertNotIn('bootstrap', self.events)
        self.assertEqual(self.agent.read_bytes(), original)
        self.assertEqual(self.bridge.state[self.kind]['agent'], str(self.agent))
        self.statuses = [self.loaded(), self.loaded(), self.absent()]
        self.launch()
        self.assertEqual(plistlib.loads(self.agent.read_bytes())['ProgramArguments'][0], '/fixture/new-python')
        self.assertEqual(self.events.count('bootstrap'), 1)

    def test_changed_loaded_identity_is_not_removed_or_overwritten(self):
        original = self.agent.read_bytes()
        self.statuses = [self.loaded(self.identity.replace('/fixture/old-python', '/unrelated/python'))]
        with self.assertRaisesRegex(setup.SetupError, 'differs'):
            self.launch()
        self.assertEqual(self.events, ['print'])
        self.assertEqual(self.agent.read_bytes(), original)

    def test_different_service_appearing_during_removal_is_left_alone(self):
        self.statuses = [self.loaded(), self.loaded(), self.loaded(self.identity.replace(str(self.agent), '/unrelated/job.plist'))]
        with self.assertRaisesRegex(setup.SetupError, 'changed during removal'):
            self.launch()
        self.assertEqual(self.events.count('bootout'), 1)
        self.assertNotIn('bootstrap', self.events)

    def test_service_changed_before_bootout_is_never_removed(self):
        original = self.agent.read_bytes()
        self.statuses = [self.loaded(), self.loaded(self.identity.replace(str(self.agent), '/unrelated/job.plist'))]
        with self.assertRaisesRegex(setup.SetupError, 'changed before removal'):
            self.launch()
        self.assertNotIn('bootout', self.events)
        self.assertNotIn('bootstrap', self.events)
        self.assertEqual(self.agent.read_bytes(), original)

    def test_failed_removal_retains_old_executable_and_retry_resumes_upgrade(self):
        original = self.agent.read_bytes()
        self.statuses = [self.loaded(), self.loaded()]
        self.removal_code = 5
        with self.assertRaisesRegex(setup.SetupError, 'removal failed'):
            self.launch()
        self.assertEqual(self.agent.read_bytes(), original)
        self.assertNotIn('bootstrap', self.events)
        self.removal_code = 0
        self.statuses = [self.loaded(), self.loaded(), self.absent()]
        self.launch()
        self.assertEqual(plistlib.loads(self.agent.read_bytes())['ProgramArguments'][0], '/fixture/new-python')
        self.assertEqual(self.events.count('bootstrap'), 1)

    def test_unknown_status_and_failed_bootout_fail_without_retry(self):
        for operation in ('status', 'bootout'):
            with self.subTest(operation=operation):
                self.events = []
                self.statuses = [subprocess.CompletedProcess([], 5, stdout='', stderr='private fixture')] if operation == 'status' else [self.loaded()]
                self.removal_code = 5
                with self.assertRaises(setup.SetupError) as error:
                    self.launch()
                self.assertNotIn('private fixture', str(error.exception))
                self.assertNotIn('bootstrap', self.events)
                self.assertLessEqual(self.events.count('bootout'), 1)

    def test_absent_service_bootstraps_once_without_bootout(self):
        self.statuses = [self.absent()]
        self.launch()
        self.assertEqual(self.events, ['print', '-lint', 'bootstrap'])

    def test_loaded_service_without_owned_plist_cannot_be_taken_over(self):
        self.agent.unlink()
        with self.assertRaisesRegex(setup.SetupError, 'unowned'):
            self.launch()
        self.assertEqual(self.events, ['print'])
        self.assertFalse(self.agent.exists())

    def test_bootstrap_failure_after_removal_is_not_retried(self):
        self.statuses = [self.loaded(), self.loaded(), self.absent()]
        self.bootstrap_error = True
        with self.assertRaisesRegex(setup.SetupError, 'bootstrap fixture failure'):
            self.launch()
        self.assertEqual(self.events.count('bootout'), 1)
        self.assertEqual(self.events.count('bootstrap'), 1)


if __name__ == '__main__': unittest.main()
