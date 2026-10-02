"""Release boundary regressions; no keys, network, launchd, or real app data."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


builder = load('build-macos')
release = load('release-macos')


class PackageBoundaryTests(unittest.TestCase):
    def test_resource_allowlist_excludes_unlisted_private_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'desktop').mkdir()
            (root / 'desktop/licenses').mkdir()
            (root / 'desktop/licenses/LICENSE.txt').write_text('Public fixture terms')
            (root / 'desktop/licenses/private.txt').write_text('Synthetic unlisted file')
            (root / 'helper.py').write_text('# public helper')
            (root / 'README.md').write_text('public guide')
            (root / 'private-token.txt').write_text('synthetic unlisted secret')
            (root / 'desktop/resources.json').write_text(json.dumps({
                'schema_version': 1, 'bridge_files': ['helper.py'], 'documentation_files': ['README.md'],
                'runtime_license_files': ['desktop/licenses/LICENSE.txt']}))
            allowlist = builder.resource_paths(root)
            self.assertEqual(set(allowlist['bridge_files'] + allowlist['documentation_files']),
                             {Path('helper.py'), Path('README.md')})
            self.assertEqual(allowlist['runtime_license_files'], [Path('desktop/licenses/LICENSE.txt')])
            for unsafe in ('../outside.txt', '/tmp/outside.txt', 'missing.py'):
                (root / 'desktop/resources.json').write_text(json.dumps({
                    'schema_version': 1, 'bridge_files': [unsafe], 'documentation_files': ['README.md'],
                    'runtime_license_files': ['desktop/licenses/LICENSE.txt']}))
                with self.assertRaises(ValueError):
                    builder.resource_paths(root)

    def test_development_and_distribution_identities_are_not_developer_id(self):
        available = ('  1) ' + 'A' * 40 + ' "Apple Development: Fixture"\n'
                     '  2) ' + 'B' * 40 + ' "Apple Distribution: Fixture"\n')
        with patch.object(builder, 'run', return_value=subprocess.CompletedProcess([], 0, stdout=available)):
            for identity in ('Apple Development: Fixture', 'Apple Distribution: Fixture', 'A' * 40):
                with self.assertRaisesRegex(ValueError, 'Developer ID Application'):
                    builder.validate_identity(identity)
        name = 'Developer ID Application: Fixture (TESTTEAM12)'
        with patch.object(builder, 'run', return_value=subprocess.CompletedProcess([], 0, stdout='1) ' + 'C' * 40 + ' "' + name + '"')):
            builder.validate_identity(name)
            builder.validate_identity('C' * 40)

    def test_release_settings_reject_identity_breaking_upgrade(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'desktop').mkdir()
            settings = json.loads((ROOT / 'desktop/release.json').read_text())
            settings['bundle_identifier'] = 'com.fixture.new-identity'
            (root / 'desktop/release.json').write_text(json.dumps(settings))
            with self.assertRaisesRegex(ValueError, 'identity'):
                builder.release_settings(root)


class FirmwareBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'source'
        self.bundle = Path(self.temporary.name) / 'bundle'
        self.root.mkdir()
        self.bundle.mkdir()
        for name in ('device_profiles.py', 'firmware.py', 'firmware.json'):
            shutil.copy2(ROOT / name, self.root / name)
        self.manifest = json.loads((self.root / 'firmware.json').read_text())
        self.profile = self.manifest['devices']['xteink_x4_pro']
        data = bytearray(128)
        data[0] = 0xE9
        data[12:14] = self.profile['chip_id'].to_bytes(2, 'little')
        self.image = bytes(data)
        self.artifact = {
            'model': self.profile['id'], 'environment': self.profile['environment'],
            'commit': self.profile['commit'], 'sha256': hashlib.sha256(self.image).hexdigest(),
            'size': len(self.image), 'bundled_path': 'desktop/firmware/' + self.profile['filename'],
            'license_notice': 'desktop/licenses/firmware/NOTICE.txt'}
        self.profile['prebuilt'] = self.artifact
        self.write(self.artifact['bundled_path'], self.image)
        self.write(self.artifact['license_notice'], b'Fixture notice. Corresponding source: passage-firmware-source.tar.gz')
        license_text = b'Fixture component terms'
        self.write('desktop/licenses/firmware/licenses/fixture-LICENSE.txt', license_text)
        self.write('desktop/licenses/firmware/licenses.json', json.dumps([{
            'source': 'source/fixture/LICENSE', 'file': 'licenses/fixture-LICENSE.txt',
            'sha256': hashlib.sha256(license_text).hexdigest()}]).encode())
        source = io.BytesIO()
        with tarfile.open(fileobj=source, mode='w:gz') as archive:
            entry = tarfile.TarInfo('source/README.md')
            content = b'Synthetic source fixture'
            entry.size = len(content)
            archive.addfile(entry, io.BytesIO(content))
        self.write('passage-firmware-source.tar.gz', source.getvalue())
        self.receipt = {
            'schema_version': 1, 'source_commit': self.profile['commit'],
            'build_succeeded': True, 'platformio': 'PlatformIO Core, version 6.2.0',
            'models': {self.profile['id']: self.artifact}, 'environments': [self.profile['environment']],
            'source_archive': {'filename': 'passage-firmware-source.tar.gz',
                               'sha256': hashlib.sha256(source.getvalue()).hexdigest(), 'size': len(source.getvalue())}}
        self.flush_manifest()

    def write(self, name, data):
        path = self.bundle / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def flush_manifest(self):
        (self.bundle / 'firmware.json').write_text(json.dumps(self.manifest))
        (self.bundle / 'firmware-build.json').write_text(json.dumps(self.receipt))

    def test_verified_assets_only_and_corresponding_source_preserved(self):
        self.write('private-unlisted.txt', b'Unlisted fixture')
        result = builder.firmware_bundle(self.bundle, self.root)
        self.assertIn(self.artifact['bundled_path'], result['bridge_files'])
        self.assertNotIn('private-unlisted.txt', result['bridge_files'])
        self.assertEqual(result['source_files']['passage-firmware-source.tar.gz'].read_bytes(),
                         (self.bundle / 'passage-firmware-source.tar.gz').read_bytes())

    def test_changed_image_is_rejected_before_packaging(self):
        self.write(self.artifact['bundled_path'], self.image[:-1] + b'X')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            builder.firmware_bundle(self.bundle, self.root)

    def test_unsuccessful_and_unpinned_build_receipts_are_rejected(self):
        for value in (None, False, 1, 'true'):
            with self.subTest(build_succeeded=value):
                self.receipt['build_succeeded'] = value
                if value is None:
                    del self.receipt['build_succeeded']
                self.flush_manifest()
                with self.assertRaisesRegex(ValueError, 'successful build'):
                    builder.firmware_bundle(self.bundle, self.root)
        self.receipt['build_succeeded'] = True
        for value in (None, '6.2.0', 'PlatformIO Core, version 6.1.18'):
            with self.subTest(platformio=value):
                self.receipt['platformio'] = value
                if value is None:
                    del self.receipt['platformio']
                self.flush_manifest()
                with self.assertRaisesRegex(ValueError, 'pinned PlatformIO'):
                    builder.firmware_bundle(self.bundle, self.root)

    def test_profile_toolchain_cannot_contradict_the_release_pin(self):
        baseline = json.loads((self.root / 'firmware.json').read_text())
        baseline['devices'][self.profile['id']]['platformio'] = '6.3.0'
        (self.root / 'firmware.json').write_text(json.dumps(baseline))
        self.profile['platformio'] = '6.3.0'
        self.flush_manifest()
        with self.assertRaisesRegex(ValueError, 'release PlatformIO pin'):
            builder.firmware_bundle(self.bundle, self.root)

    def test_corresponding_source_and_license_corruption_are_rejected(self):
        for name in ('passage-firmware-source.tar.gz', 'desktop/licenses/firmware/licenses/fixture-LICENSE.txt'):
            path = self.bundle / name
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                builder.firmware_bundle(self.bundle, self.root)
            path.write_bytes(original)

    def test_registry_pin_and_processor_cannot_be_changed_by_assets(self):
        for field, value in (('commit', 'f' * 40), ('chip_id', 5)):
            original = self.profile[field]
            self.profile[field] = value
            self.flush_manifest()
            with self.assertRaisesRegex(ValueError, 'registry'):
                builder.firmware_bundle(self.bundle, self.root)
            self.profile[field] = original
        self.flush_manifest()


class DistributionGateTests(unittest.TestCase):
    def setUp(self):
        self.candidate = {
            'commit': 'a' * 40, 'version': '0.7.0', 'architecture': 'arm64',
            'artifact': {'sha256': 'b' * 64},
            'reader_profiles': [{'id': 'kindle', 'kind': 'kindle', 'prebuilt_ready': True},
                                {'id': 'xteink_x4_pro', 'kind': 'xteink', 'prebuilt_ready': False}]}
        self.acceptance = {
            'schema_version': 1, 'scope': 'clean-mac-without-developer-tools',
            'commit': 'a' * 40, 'version': '0.7.0', 'architecture': 'arm64',
            'artifact_sha256': 'b' * 64, 'macos_version': '13.0', 'tested_at': '2026-10-02',
            'checks': {name: {'passed': True, 'evidence': 'Synthetic test evidence'} for name in release.CHECKS},
            'readers': [{'profile_id': 'kindle', 'passed': True, 'evidence': 'Synthetic fixture description'}]}

    def test_single_reader_does_not_require_a_second_reader_or_position_service(self):
        self.assertEqual(release.validate_acceptance(self.candidate, self.acceptance), ['kindle'])

    def test_namespace_acceptance_cannot_claim_a_clean_mac(self):
        self.acceptance['scope'] = 'isolated-data-and-service-namespace'
        with self.assertRaisesRegex(ValueError, 'separate clean-Mac'):
            release.validate_acceptance(self.candidate, self.acceptance)

    def test_changed_download_and_incomplete_observations_are_rejected(self):
        self.acceptance['artifact_sha256'] = 'c' * 64
        with self.assertRaisesRegex(ValueError, 'artifact_sha256'):
            release.validate_acceptance(self.candidate, self.acceptance)
        self.acceptance['artifact_sha256'] = 'b' * 64
        self.acceptance['checks']['collector_login_restart']['passed'] = False
        with self.assertRaisesRegex(ValueError, 'collector_login_restart'):
            release.validate_acceptance(self.candidate, self.acceptance)

    def test_firmware_unavailable_and_unknown_profiles_cannot_be_claimed(self):
        for identity, message in (('xteink_x4_pro', 'prebuilt'), ('unknown_reader', 'Unknown')):
            self.acceptance['readers'] = [{'profile_id': identity, 'passed': True, 'evidence': 'Fixture'}]
            with self.assertRaisesRegex(ValueError, message):
                release.validate_acceptance(self.candidate, self.acceptance)

    def test_multiple_readers_require_actual_progress_roundtrip_evidence(self):
        self.candidate['reader_profiles'][1]['prebuilt_ready'] = True
        self.acceptance['readers'].append({'profile_id': 'xteink_x4_pro', 'passed': True, 'evidence': 'Fixture'})
        with self.assertRaisesRegex(ValueError, 'round trip'):
            release.validate_acceptance(self.candidate, self.acceptance)
        self.acceptance['checks']['progress_roundtrip'] = {'passed': True, 'evidence': 'Fixture in both directions'}
        self.assertEqual(release.validate_acceptance(self.candidate, self.acceptance), ['kindle', 'xteink_x4_pro'])

    def test_finalization_cannot_remove_or_change_signed_source_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / 'Passage.dmg'
            artifact.write_bytes(b'Synthetic download')
            source = {'filename': 'passage-firmware-source.tar.gz', 'sha256': 'f' * 64, 'size': 123}
            build = {key: self.candidate[key] for key in ('commit', 'version', 'architecture')}
            build.update(source_dirty=False, distribution='release-candidate', firmware_source=source)
            resources = root / 'Passage.app/Contents/Resources'
            resources.mkdir(parents=True)
            (resources / 'build.json').write_text(json.dumps(build))
            candidate = copy.deepcopy(self.candidate)
            candidate.update(schema_version=1, state='notarized-candidate', reader_profiles=release.profiles(build),
                             artifact={'filename': artifact.name, 'sha256': release.digest(artifact)},
                             automated_acceptance={**build, 'passed': True, 'scope': 'isolated-data-and-service-namespace'},
                             notarization={'app': {'status': 'Accepted'}, 'dmg': {'status': 'Accepted'}})
            path = root / 'release-candidate.json'
            acceptance = root / 'acceptance.json'
            acceptance.write_text(json.dumps(self.acceptance))
            for changed in (None, {**source, 'filename': 'other-source.tar.gz'}):
                with self.subTest(source=changed):
                    candidate['firmware_source'] = changed
                    path.write_text(json.dumps(candidate))
                    with patch.object(release, 'assess') as assess:
                        with self.assertRaisesRegex(ValueError, 'firmware source differs'):
                            release.finalize(path, acceptance)
                        assess.assert_not_called()
                    self.assertFalse((root / 'release-manifest.json').exists())

    def test_accepted_zip_staples_the_app_and_rejected_notary_never_staples(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def response(*args, **kwargs):
                return subprocess.CompletedProcess(args, 0, stdout=json.dumps({'id': 'fixture-id', 'status': 'Accepted'}))
            with patch.object(release, 'run', side_effect=response) as commands:
                result = release.notarize(root / 'app.zip', 'fixture-profile', root / 'notary.json', staple_target=root / 'Passage.app')
                self.assertTrue(result['stapled'])
                commands.assert_any_call('xcrun', 'stapler', 'staple', root / 'Passage.app', capture_output=True)
                self.assertFalse(any(call.args[:3] == ('xcrun', 'stapler', 'staple') and call.args[3] == root / 'app.zip' for call in commands.call_args_list))
            with patch.object(release, 'run', return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps({'id': 'fixture-id', 'status': 'Invalid'}))) as commands:
                with self.assertRaisesRegex(ValueError, 'did not accept'):
                    release.notarize(root / 'image.dmg', 'fixture-profile', root / 'rejected.json')
                self.assertFalse(any('stapler' in call.args for call in commands.call_args_list))


class SignatureGateTests(unittest.TestCase):
    def setUp(self):
        self.details = ('Authority=Developer ID Application: Fixture (TESTTEAM12)\n'
                        'CodeDirectory v=20500 flags=0x10000(runtime)\n'
                        'Timestamp=Oct 2, 2026 at 12:00:00\n'
                        'TeamIdentifier=TESTTEAM12\nCDHash=' + 'a' * 40 + '\n')
        self.entitlements = {}

    def command(self, *args, **kwargs):
        if '--entitlements' in args:
            return subprocess.CompletedProcess(args, 0, stdout=plistlib.dumps(self.entitlements))
        return subprocess.CompletedProcess(args, 0, stdout='', stderr=self.details)

    def test_developer_id_runtime_timestamp_and_identity_are_recorded(self):
        with patch.object(release, 'run', side_effect=self.command):
            self.assertEqual(release.signature(Path('Passage.app')), {
                'team_identifier': 'TESTTEAM12', 'cdhash': 'a' * 40,
                'hardened_runtime': True, 'secure_timestamp': True})

    def test_debug_entitlement_is_rejected(self):
        self.entitlements['com.apple.security.get-task-allow'] = True
        with patch.object(release, 'run', side_effect=self.command):
            with self.assertRaisesRegex(ValueError, 'Debug entitlement'):
                release.signature(Path('Passage.app'))

    def test_incomplete_distribution_signatures_are_rejected(self):
        original = self.details
        for marker in ('Authority=Developer ID Application:', 'flags=0x10000(runtime)', 'Timestamp='):
            with self.subTest(missing=marker):
                self.details = original.replace(marker, 'missing=')
                with patch.object(release, 'run', side_effect=self.command):
                    with self.assertRaisesRegex(ValueError, 'App lacks Developer ID'):
                        release.signature(Path('Passage.app'))


if __name__ == '__main__':
    unittest.main()
