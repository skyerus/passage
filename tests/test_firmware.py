import contextlib
import copy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import device_profiles
import firmware
import setup


def image(chip=9):
    data = bytearray(64)
    data[0] = 0xE9
    data[12:14] = chip.to_bytes(2, 'little')
    return bytes(data)


def artifact(spec, data, bundled=False):
    spec = copy.deepcopy(spec)
    spec['prebuilt'] = {'model': spec['id'], 'environment': spec['environment'], 'commit': spec['commit'],
                       'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data),
                       'license_notice': 'desktop/licenses/firmware/NOTICE.txt'}
    if bundled:
        spec['prebuilt']['bundled_path'] = 'desktop/firmware/' + spec['filename']
    else:
        spec['prebuilt']['url'] = 'https://github.com/skyerus/crosspoint-reader/releases/download/test-v1/' + spec['filename']
    return spec


class FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.bridge = setup.Bridge(self.root / 'app', agent_dir=self.root / 'agents')
        self.spec = artifact(device_profiles.profile('xteink_x4_pro'), image())
        setup.atomic_write(self.root / self.spec['prebuilt']['license_notice'], b'Fixture notice')

    def tearDown(self):
        self.temp.cleanup()

    def test_hash_and_processor_checked_before_any_reader_write(self):
        spec = artifact(device_profiles.profile('xteink_x4_pro'), image(5))
        with self.assertRaisesRegex(firmware.FirmwareError, 'different processor'):
            firmware.verify(image(5), spec)
        for data in (image()[:-1], image() + b'extra', b'corrupted' * 8):
            with self.assertRaisesRegex(firmware.FirmwareError, 'checksum mismatch'):
                firmware.verify(data, self.spec)

    def test_manifest_model_revision_and_environment_mismatches_refused(self):
        for field, value in (('model', 'xteink_x4'), ('environment', 'default'), ('commit', 'a' * 40)):
            spec = copy.deepcopy(self.spec)
            spec['prebuilt'][field] = value
            with self.assertRaisesRegex(firmware.FirmwareError, 'does not match'):
                firmware.prebuilt_spec(spec)

    def test_release_download_and_redirect_hosts_are_restricted(self):
        for url in ('http://github.com/file.bin', 'https://evil.example/file.bin',
                    'https://github.com@evil.example/file.bin', 'https://github.com:444/file.bin'):
            with self.assertRaises(firmware.FirmwareError):
                firmware.release_url(url)
        self.assertEqual(firmware.release_url('https://release-assets.githubusercontent.com/asset?signature=example'),
                         'https://release-assets.githubusercontent.com/asset?signature=example')
        for url in ('https://github.com/skyerus/crosspoint-reader/releases/latest/file.bin',
                    'https://github.com/other/repo/releases/download/v1/file.bin'):
            with self.assertRaises(firmware.FirmwareError):
                firmware.release_url(url, asset=True)

    def test_available_requires_packaged_redistribution_notice(self):
        self.assertTrue(firmware.available(self.spec, self.root))
        (self.root / self.spec['prebuilt']['license_notice']).unlink()
        self.assertFalse(firmware.available(self.spec, self.root))
        for model in device_profiles.public_profiles():
            self.assertFalse(model['firmware_available'])

    def test_bundled_image_needs_no_network_or_developer_tools(self):
        spec = artifact(device_profiles.profile('xteink_x4_pro'), image(), bundled=True)
        setup.atomic_write(self.root / spec['prebuilt']['bundled_path'], image())
        self.assertTrue(firmware.available(spec, self.root))
        with patch.object(setup, 'SOURCE', self.root), patch.object(setup, 'run', side_effect=AssertionError('No developer commands')), patch.object(firmware, 'download', side_effect=AssertionError('No network')):
            self.assertEqual(self.bridge.delivered_firmware(spec), image())

    def test_download_caches_only_verified_bytes_and_revalidates_cache(self):
        with patch.object(setup, 'SOURCE', self.root), patch.object(firmware, 'download', return_value=image()) as download:
            self.assertEqual(self.bridge.delivered_firmware(self.spec), image())
            self.assertEqual(self.bridge.delivered_firmware(self.spec), image())
        download.assert_called_once()
        cache = self.bridge.app / 'firmware' / self.spec['prebuilt']['sha256'] / self.spec['filename']
        cache.write_bytes(b'bad')
        with patch.object(setup, 'SOURCE', self.root):
            with self.assertRaisesRegex(setup.SetupError, 'checksum mismatch'):
                self.bridge.delivered_firmware(self.spec)

    def test_bad_download_never_caches_or_stages_firmware(self):
        with patch.object(setup, 'SOURCE', self.root), patch.object(firmware, 'download', return_value=b'corrupt'):
            with self.assertRaisesRegex(setup.SetupError, 'checksum mismatch'):
                self.bridge.delivered_firmware(self.spec)
        self.assertFalse((self.bridge.app / 'firmware').exists())

    def test_no_prebuilt_does_not_fall_back_to_source_or_modify_reader(self):
        card = self.root / 'card'
        (card / '.crosspoint').mkdir(parents=True)
        with patch.object(self.bridge, 'build_firmware', side_effect=AssertionError('Source fallback')), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(setup.SetupError, 'not available'):
                self.bridge.xteink(mount=card, model='xteink_x4_pro', firmware=True)
        self.assertEqual(list((card / '.crosspoint').iterdir()), [])
        self.assertFalse(self.bridge.state_path.exists())

    def test_path_traversal_and_multiple_delivery_sources_refused(self):
        for field, value in (('license_notice', 'desktop/licenses/firmware/../../private.txt'),
                             ('bundled_path', 'desktop/firmware/../../private.bin')):
            spec = artifact(device_profiles.profile('xteink_x4_pro'), image(), bundled=True)
            spec['prebuilt'][field] = value
            with self.assertRaises(firmware.FirmwareError):
                firmware.prebuilt_spec(spec)
        self.spec['prebuilt']['bundled_path'] = 'desktop/firmware/duplicate.bin'
        with self.assertRaises(firmware.FirmwareError):
            firmware.prebuilt_spec(self.spec)


if __name__ == '__main__':
    unittest.main()
