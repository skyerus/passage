import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import desktop
import device_profiles
import setup


class DeviceProfilesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.bridge = setup.Bridge(self.root / 'app', agent_dir=self.root / 'agents')
        setup.atomic_write(self.bridge.app / 'collector/data/token', b'x' * 43)

    def tearDown(self):
        self.temp.cleanup()

    def card(self, name):
        path = self.root / name
        (path / '.crosspoint').mkdir(parents=True)
        return path

    def test_every_pinned_hardware_environment_has_explicit_profile(self):
        rows = device_profiles.registry()
        self.assertEqual(set(rows), {'xteink_x3', 'xteink_x4', 'xteink_x4_pro', 'xteink_x4_classic', 'sticky', 'm5stack_paper_mono'})
        self.assertEqual({row['environment'] for row in rows.values()}, {'default', 'x4pro', 'x4c', 'sticky', 'papermono'})
        for model in ('xteink_x3', 'xteink_x4', 'xteink_x4_classic'):
            self.assertFalse(rows[model]['capabilities']['touch'])
            self.assertTrue(rows[model]['capabilities']['highlights'])
            self.assertTrue(rows[model]['capabilities']['progress'])
            self.assertIn('confirm buttons', rows[model]['firmware_update_instructions'])
        for model in ('xteink_x4_pro', 'sticky', 'm5stack_paper_mono'):
            self.assertTrue(rows[model]['capabilities']['touch'])

    def test_actual_firmware_api_names_route_without_guessing(self):
        for model, spec in device_profiles.registry().items():
            for alias in spec['api_models']:
                self.assertEqual(device_profiles.model_from_status({'device': alias}), model)
        self.assertIsNone(device_profiles.model_from_status({'device': 'X4Pro-ish'}))
        self.assertIsNone(device_profiles.model_from_status({'name': 'X4'}))

    def test_each_model_pairs_and_keeps_its_own_device_identity(self):
        ids = []
        for model in device_profiles.registry():
            card = self.card(model)
            with contextlib.redirect_stdout(io.StringIO()):
                self.bridge.xteink(mount=card, model=model, url='http://mac.local:8084')
            config = json.loads((card / '.crosspoint/highlight-sync.json').read_text())
            ids.append(config['device_id'])
            self.assertEqual(self.bridge.state['xteink']['model'], model)
            self.assertEqual(json.loads((card / '.crosspoint/passage-device.json').read_text())['model'], model)
        self.assertEqual(len(ids), len(set(ids)))

    def test_sd_receipt_model_mismatch_does_not_touch_config_or_state(self):
        card = self.card('card')
        setup.atomic_write(card / '.crosspoint/passage-device.json', b'{"model":"xteink_x4"}')
        before = dict(self.bridge.state)
        with self.assertRaisesRegex(setup.SetupError, 'different model'):
            self.bridge.xteink(mount=card, model='xteink_x4_pro', url='http://mac.local:8084', firmware=True)
        self.assertEqual(self.bridge.state, before)
        self.assertFalse((card / '.crosspoint/highlight-sync.json').exists())
        self.assertFalse(any(card.glob('*.bin')))

    def test_http_mismatch_blocks_firmware_delivery_and_pairing(self):
        with patch.object(setup, 'http', return_value=b'{"device":"X4"}'), patch.object(self.bridge, 'delivered_firmware') as delivery:
            with self.assertRaisesRegex(setup.SetupError, 'does not match'):
                self.bridge.xteink(device_url='http://192.168.1.4', model='xteink_x3', url='http://mac.local:8084', firmware=True)
        delivery.assert_not_called()
        self.assertNotIn('xteink', self.bridge.state)

    def test_missing_selected_model_refused_without_guessing(self):
        card = self.card('card')
        with self.assertRaises(setup.SetupError):
            self.bridge.xteink(mount=card, url='http://mac.local:8084')
        self.assertFalse((card / '.crosspoint/highlight-sync.json').exists())

    def test_legacy_x4_pro_state_and_identity_are_preserved(self):
        self.bridge.state = {'xteink': {'paired': True, 'firmware_staged': True}, 'devices': {'crosspoint': 'legacy-id'}}
        self.bridge.save()
        desktop_bridge = desktop.Desktop(self.bridge.app, agent_dir=self.bridge.agent_dir)
        with patch.object(desktop_bridge, 'existing', return_value=({'connected': False, 'healthy': False}, None)):
            status = desktop_bridge.status()
        self.assertEqual(status['xteink']['model'], 'xteink_x4_pro')
        self.assertEqual(json.loads(self.bridge.state_path.read_text())['xteink'], {'paired': True, 'firmware_staged': True})
        card = self.card('legacy')
        with contextlib.redirect_stdout(io.StringIO()):
            self.bridge.xteink(mount=card, model='xteink_x4_pro', url='http://mac.local:8084')
        self.assertEqual(json.loads((card / '.crosspoint/highlight-sync.json').read_text())['device_id'], 'legacy-id')
        self.assertTrue(self.bridge.state['xteink']['firmware_staged'])
        self.assertEqual(self.bridge.state['xteink']['model'], 'xteink_x4_pro')

    def test_progress_only_profile_does_not_install_highlight_credentials(self):
        spec = device_profiles.profile('xteink_x4')
        spec['capabilities']['highlights'] = False
        card = self.card('progress-only')
        (self.bridge.app / 'collector/data/token').unlink()
        with patch.object(self.bridge, 'device_profile', return_value=spec), contextlib.redirect_stdout(io.StringIO()):
            self.bridge.xteink(mount=card, model=spec['id'])
        self.assertFalse((card / '.crosspoint/highlight-sync.json').exists())
        self.assertEqual(self.bridge.state['xteink']['model'], spec['id'])

    def test_desktop_requires_exact_model_even_after_confirmation(self):
        bridge = desktop.Desktop(self.bridge.app, agent_dir=self.bridge.agent_dir)
        with patch.object(bridge, 'xteink') as pair:
            with self.assertRaises(setup.SetupError):
                bridge.mutate('pair_xteink', {'model_confirmed': True, 'mount': '/card'})
        pair.assert_not_called()


if __name__ == '__main__':
    unittest.main()
