"""Integrity-verified firmware delivery from the manifest bundled with Passage.

No remote manifest can change the selected model, source revision or digest.
Source builds are an explicit developer operation in setup.py.
"""
import hashlib
from pathlib import Path
import re
from urllib import request, parse

MAX_FIRMWARE = 32 * 1024 * 1024
ALLOWED_HOSTS = {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}


class FirmwareError(ValueError):
    pass


def release_url(value, asset=False):
    if not isinstance(value, str):
        raise FirmwareError('Firmware download address is missing.')
    try:
        url = parse.urlsplit(value)
        port = url.port
    except ValueError as exc:
        raise FirmwareError('Firmware download address is invalid.') from exc
    if (url.scheme != 'https' or url.hostname not in ALLOWED_HOSTS or url.username or url.password
            or port not in (None, 443) or url.fragment):
        raise FirmwareError('Firmware downloads must use the approved HTTPS release service.')
    if asset and (url.hostname != 'github.com' or url.query or
                  not re.fullmatch(r'/skyerus/crosspoint-reader/releases/download/[^/]+/[^/]+\.bin', url.path)
                  or '/latest/' in url.path):
        raise FirmwareError('Firmware must reference an immutable Passage release asset.')
    return value


def prebuilt_spec(profile):
    spec = profile.get('prebuilt')
    if not isinstance(spec, dict):
        raise FirmwareError('A reviewed firmware download is not available for this model in this release. Pair an existing Passage firmware installation, or wait for an updated Passage release.')
    if any(spec.get(key) != profile.get(key) for key in ('environment', 'commit')) or spec.get('model') != profile.get('id'):
        raise FirmwareError('Firmware does not match the selected model and source revision.')
    if not re.fullmatch(r'[a-f0-9]{40}', spec.get('commit', '')) or not re.fullmatch(r'[a-f0-9]{64}', spec.get('sha256', '')):
        raise FirmwareError('Firmware source revision or checksum is invalid.')
    if type(spec.get('size')) is not int or not 24 <= spec['size'] <= MAX_FIRMWARE:
        raise FirmwareError('Firmware size is invalid.')
    filename = profile.get('filename', '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]*\.bin', filename):
        raise FirmwareError('Firmware filename does not match this model.')
    if bool(spec.get('url')) == bool(spec.get('bundled_path')):
        raise FirmwareError('Choose exactly one firmware release asset or bundled image.')
    if spec.get('url'):
        if parse.urlsplit(release_url(spec['url'], asset=True)).path.rsplit('/', 1)[-1] != filename:
            raise FirmwareError('Firmware filename does not match this model.')
    else:
        bundled = spec['bundled_path']
        if not isinstance(bundled, str) or not bundled.startswith('desktop/firmware/') or '..' in Path(bundled).parts or Path(bundled).suffix != '.bin':
            raise FirmwareError('Bundled firmware path is invalid.')
    notice = spec.get('license_notice')
    if not isinstance(notice, str) or not notice.startswith('desktop/licenses/firmware/') or '..' in Path(notice).parts or Path(notice).suffix != '.txt':
        raise FirmwareError('Firmware redistribution notice is missing.')
    return spec


def available(profile, source=None):
    source = Path(source or Path(__file__).parent)
    try:
        spec = prebuilt_spec(profile)
        notice = source / spec['license_notice']
        if not notice.is_file() or not notice.read_text().strip():
            return False
        return not spec.get('bundled_path') or (source / spec['bundled_path']).is_file()
    except (FirmwareError, OSError, UnicodeError):
        return False


def verify(data, profile):
    spec = prebuilt_spec(profile)
    if len(data) != spec['size'] or hashlib.sha256(data).hexdigest() != spec['sha256']:
        raise FirmwareError('Firmware checksum mismatch. Nothing was staged; retry the download.')
    # ESP application image header stores the MCU identifier at bytes 12-13.
    if data[0] != 0xE9 or int.from_bytes(data[12:14], 'little') != profile.get('chip_id'):
        raise FirmwareError('Firmware image is for a different processor. Nothing was staged.')
    return data


class HTTPSRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        release_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(profile, timeout=300):
    spec = prebuilt_spec(profile)
    if not spec.get('url'):
        raise FirmwareError('This firmware is supplied by the app bundle; use its verified local image.')
    opener = request.build_opener(HTTPSRedirect(), request.ProxyHandler({}))
    with opener.open(request.Request(spec['url'], headers={'User-Agent': 'Passage-firmware'}), timeout=timeout) as response:
        release_url(response.geturl())
        data = response.read(spec['size'] + 1)
    return verify(data, profile)
