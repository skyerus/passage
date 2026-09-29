import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
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
        for archive in ('skyerus/kindle-highlights', 'skyerus/reader-bridge', ''):
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
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup, 'run', side_effect=setup.SetupError('lint failed')):
            with self.assertRaises(setup.SetupError):
                self.bridge.launch('collector', ['/usr/bin/python3', 'collector.py'], self.bridge.app)
        resumed = setup.Bridge(self.bridge.app, agent_dir=self.bridge.agent_dir)
        self.assertEqual(resumed.state['collector']['agent'], str(resumed.agent_path('collector')))
        with patch.object(setup.sys, 'platform', 'darwin'), patch.object(setup, 'run', return_value=''), patch.object(setup.subprocess, 'run'):
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
        directory = self.bridge.app / 'builds' / spec['commit']
        source = directory / 'source'; source.mkdir(parents=True)
        setup.atomic_write(source / 'platformio.local.ini', b'[env:x4pro]\nextra_scripts=untrusted.py')
        setup.atomic_write(directory / 'venv/bin/python', b'fixture')
        with patch.object(setup, 'run', side_effect=['', spec['commit'] + '\n']), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(setup.SetupError): self.bridge.build_firmware(spec)


if __name__ == '__main__': unittest.main()
