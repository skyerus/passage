"""Release-owned CrossPoint hardware profiles; no device is inferred from its name."""
import copy
import json
from pathlib import Path
import re

MANIFEST = Path(__file__).with_name('firmware.json')
LEGACY_MODEL = 'xteink_x4_pro'


class ProfileError(ValueError):
    pass


def registry(path=None):
    manifest = json.loads(Path(path or MANIFEST).read_text())
    if manifest.get('schema_version') != 2 or not isinstance(manifest.get('devices'), dict):
        raise ProfileError('Unsupported device registry. Update Passage before pairing.')
    devices = manifest['devices']
    for model, profile in devices.items():
        if not re.fullmatch(r'[a-z][a-z0-9_]{1,63}', model) or not isinstance(profile, dict):
            raise ProfileError('Invalid device profile in this release.')
        if profile.get('id') != model or not isinstance(profile.get('name'), str):
            raise ProfileError('Device profile identity is invalid.')
        capabilities = profile.get('capabilities', {})
        if any(type(capabilities.get(key)) is not bool for key in ('highlights', 'progress', 'touch')):
            raise ProfileError('Device capabilities are invalid.')
        if type(profile.get('pairing_supported')) is not bool:
            raise ProfileError('Device pairing support is invalid.')
        if (not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', profile.get('environment', '')) or
                not re.fullmatch(r'[a-f0-9]{40}', profile.get('commit', '')) or
                not re.fullmatch(r'[a-z0-9][a-z0-9._-]*\.bin', profile.get('filename', '')) or
                type(profile.get('chip_id')) is not int or profile['chip_id'] < 0):
            raise ProfileError('Device firmware target is invalid.')
        aliases = profile.get('api_models')
        if not isinstance(aliases, list) or not aliases or any(not isinstance(x, str) or not x for x in aliases):
            raise ProfileError('Device model identifiers are invalid.')
    aliases = [alias for profile in devices.values() for alias in profile['api_models']]
    if len(aliases) != len(set(aliases)):
        raise ProfileError('Device model identifiers overlap.')
    return devices


def profile(model, path=None):
    devices = registry(path)
    if not isinstance(model, str) or model not in devices:
        raise ProfileError('Select your exact CrossPoint model before pairing. Do not flash another model.')
    result = copy.deepcopy(devices[model])
    if not result['pairing_supported']:
        raise ProfileError(result.get('support_note') or 'This model is not supported by this Passage release.')
    return result


def model_from_status(status, path=None):
    if not isinstance(status, dict):
        return None
    for model, spec in registry(path).items():
        if status.get('device') in spec['api_models']:
            return model
    return None


def saved_model(saved):
    """Only old successfully paired installs can be known to have been X4 Pro."""
    if not isinstance(saved, dict):
        return None
    return saved.get('model') or (LEGACY_MODEL if saved.get('paired') or saved.get('paired_at') else None)


def public_profiles(path=None):
    # Import here keeps firmware validation independent of public presentation.
    import firmware
    result = []
    for spec in registry(path).values():
        row = {key: spec[key] for key in ('id', 'name', 'capabilities', 'pairing_supported',
               'filename', 'setup_url', 'firmware_update_instructions', 'support_note') if key in spec}
        row['firmware_filename'] = row.pop('filename', None)
        try:
            row['firmware_available'] = firmware.available(spec)
        except firmware.FirmwareError:
            row['firmware_available'] = False
        row['source_build_available'] = bool(spec.get('commit') and spec.get('environment'))
        if not row['firmware_available']:
            row['support_note'] = (spec.get('support_note', '') + ' Pair an existing Passage firmware installation. A reviewed firmware download is not available in this release.').strip()
        result.append(row)
    return result
