import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('firmware_assets', Path(__file__).resolve().parents[1] / 'scripts/build-firmware-assets.py')
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


class FirmwareAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        def git(*args):
            return subprocess.run(['git', '-C', str(self.source), *args], check=True, capture_output=True, text=True).stdout.strip()
        git('init')
        (self.source / 'main.cpp').write_text('// Public firmware fixture\n')
        git('add', 'main.cpp')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture')
        self.commit = git('rev-parse', 'HEAD')
        (self.source / 'private.txt').write_text('PRIVATE_UNTRACKED_SENTINEL')
        binary = self.source / '.pio/build/example/firmware.bin'
        binary.parent.mkdir(parents=True)
        image = bytearray(256)
        image[0] = 0xE9
        image[12] = 9
        binary.write_bytes(image)
        self.binary = binary
        dep = self.source / '.pio/libdeps/example/Example'
        dep.mkdir(parents=True)
        (dep / 'LICENSE').write_text('Example public library license fixture')
        for name in ('framework-arduinoespressif32', 'framework-espidf', 'framework-arduinoespressif32-libs'):
            framework = self.root / 'core/packages' / name
            framework.mkdir(parents=True)
            (framework / 'LICENSE').write_text('Example public framework license fixture: ' + name)
        platform = self.root / 'core/platforms/espressif32'
        platform.mkdir(parents=True)
        (platform / 'builder.py').write_text('# Public build script fixture\n')
        self.manifest = self.root / 'manifest.json'
        self.data = {'schema_version': 2, 'devices': {'example_reader': {
            'id': 'example_reader', 'commit': self.commit, 'environment': 'example',
            'chip_id': 9, 'filename': 'passage-example.bin', 'prebuilt': None}}}
        self.manifest.write_text(json.dumps(self.data))
        self.args = argparse.Namespace(source=self.source, manifest=self.manifest, output=self.root / 'output',
            platformio_core=self.root / 'core', models=None, pio='fixture-pio', jobs=4)
        inner = self.root / 'core/penv/bin/python'
        inner.parent.mkdir(parents=True)
        inner.touch()
        actual_run = assets.run
        def fake_build(*args, **kwargs):
            if str(args[0]) in ('fixture-pio', str(inner), str(inner.with_name('pio'))):
                return subprocess.CompletedProcess(args, 0, stdout='PlatformIO Core, version 6.1.19', stderr='')
            return actual_run(*args, **kwargs)
        self.run_patch = patch.object(assets, 'run', side_effect=fake_build)
        self.run_mock = self.run_patch.start()
        self.addCleanup(self.run_patch.stop)

    def test_bundle_matches_binary_and_excludes_untracked_data(self):
        assets.assemble(self.args)
        output = self.args.output
        manifest = json.loads((output / 'firmware.json').read_text())
        prebuilt = manifest['devices']['example_reader']['prebuilt']
        self.assertEqual(prebuilt['sha256'], hashlib.sha256(self.binary.read_bytes()).hexdigest())
        self.assertEqual((output / prebuilt['bundled_path']).read_bytes(), self.binary.read_bytes())
        receipt = json.loads((output / 'firmware-build.json').read_text())
        archive_path = output / receipt['source_archive']['filename']
        self.assertEqual(assets.digest(archive_path), receipt['source_archive']['sha256'])
        with tarfile.open(archive_path) as archive:
            names = archive.getnames()
            self.assertIn('source/main.cpp', names)
            self.assertNotIn('source/private.txt', names)
            self.assertIn('source/.pio/libdeps/example/Example/LICENSE', names)
            self.assertIn('platform-espressif32/builder.py', names)
        self.assertEqual(len(json.loads((output / 'desktop/licenses/firmware/licenses.json').read_text())), 4)
        self.assertTrue(receipt['build_succeeded'])

    def test_wrong_chip_leaves_no_deliverable(self):
        data = bytearray(self.binary.read_bytes())
        data[12] = 5
        self.binary.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'Invalid application'):
            assets.assemble(self.args)
        self.assertFalse(self.args.output.exists())

    def test_unrecognized_build_override_is_preserved(self):
        override = self.source / 'platformio.local.ini'
        override.write_text('[env:example]\nextra_scripts = private.py\n')
        with self.assertRaisesRegex(ValueError, 'Unrecognized local'):
            assets.assemble(self.args)
        self.assertIn('private.py', override.read_text())
        self.assertFalse(self.args.output.exists())

    def test_nested_core_must_match_pinned_version(self):
        previous = self.run_mock.side_effect
        def mismatch(*args, **kwargs):
            if str(args[0]).endswith('/penv/bin/pio'):
                return subprocess.CompletedProcess(args, 0, stdout='PlatformIO Core, version 6.2.0')
            return previous(*args, **kwargs)
        self.run_mock.side_effect = mismatch
        with self.assertRaisesRegex(ValueError, 'Nested firmware build core'):
            assets.assemble(self.args)
        self.assertFalse(self.args.output.exists())

    def test_source_revision_mismatch_rejected(self):
        self.data['devices']['example_reader']['commit'] = 'a' * 40
        self.manifest.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(ValueError, 'pinned source'):
            assets.assemble(self.args)
        self.assertFalse(self.args.output.exists())

    def test_manifest_cannot_escape_bundle_directory(self):
        self.data['devices']['example_reader']['filename'] = '../escape.bin'
        self.manifest.write_text(json.dumps(self.data))
        with self.assertRaisesRegex(ValueError, 'Invalid firmware target'):
            assets.assemble(self.args)
        self.assertFalse(self.args.output.exists())

    def test_build_failure_cannot_package_old_binary(self):
        previous = self.run_mock.side_effect
        def failed(*args, **kwargs):
            if args[:2] == ('fixture-pio', 'run'):
                raise subprocess.CalledProcessError(1, args)
            return previous(*args, **kwargs)
        self.run_mock.side_effect = failed
        with self.assertRaises(subprocess.CalledProcessError):
            assets.assemble(self.args)
        self.assertFalse(self.args.output.exists())

    def test_source_mutation_during_build_is_rejected(self):
        previous = self.run_mock.side_effect
        def changed(*args, **kwargs):
            result = previous(*args, **kwargs)
            if args[:2] == ('fixture-pio', 'run'):
                (self.source / 'main.cpp').write_text('changed while building')
            return result
        self.run_mock.side_effect = changed
        with self.assertRaisesRegex(ValueError, 'changed during the build'):
            assets.assemble(self.args)
        self.assertFalse(self.args.output.exists())


if __name__ == '__main__':
    unittest.main()
