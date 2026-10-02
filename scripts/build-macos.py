#!/usr/bin/env python3
"""Build a self-contained Passage.app; no Python required on the user's Mac."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MACHO = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def release_settings(root=ROOT):
    value = json.loads((root / 'desktop/release.json').read_text())
    if (value.get('schema_version') != 1
            or not re.fullmatch(r'\d+\.\d+\.\d+', value.get('version', ''))
            or not re.fullmatch(r'\d+', value.get('build', ''))
            or value.get('minimum_macos') != '13.0'
            or value.get('bundle_identifier') != 'com.readerbridge.desktop'):
        raise ValueError('Invalid release settings or incompatible application identity')
    return value


def resource_paths(root=ROOT):
    """Resolve only reviewed, explicit resources; never copy a source tree."""
    manifest = json.loads((root / 'desktop/resources.json').read_text())
    if manifest.get('schema_version') != 1:
        raise ValueError('Unsupported resource manifest')
    seen = set()
    groups = {}
    for group in ('bridge_files', 'documentation_files', 'runtime_license_files'):
        groups[group] = []
        if not isinstance(manifest.get(group), list) or not manifest[group]:
            raise ValueError('Empty resource allowlist: ' + group)
        for name in manifest[group]:
            if not isinstance(name, str):
                raise ValueError('Resource names must be strings')
            relative = Path(name)
            if group == 'runtime_license_files' and relative.parts[:2] != ('desktop', 'licenses'):
                raise ValueError('Runtime license is outside the approved notices directory')
            source = root / relative
            if (not isinstance(name, str) or relative.is_absolute()
                    or '..' in relative.parts or name in seen
                    or any(part in {'.git', '__pycache__', 'tests', 'progress-tests'} for part in relative.parts)
                    or source.is_symlink() or not source.is_file()
                    or not source.resolve().is_relative_to(root.resolve())):
                raise ValueError('Missing or unsafe allowlisted resource: ' + str(name))
            seen.add(name)
            groups[group].append(relative)
    return groups


def bundle_file(bundle, name):
    relative = Path(name)
    source = bundle / relative
    if (relative.is_absolute() or '..' in relative.parts or source.is_symlink()
            or not source.is_file() or not source.resolve().is_relative_to(bundle.resolve())):
        raise ValueError('Missing or unsafe firmware bundle file: ' + str(name))
    return source


def file_digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def firmware_bundle(bundle, root=ROOT):
    """Validate generated assets; only listed files enter the signed app."""
    bundle = bundle.expanduser().resolve()
    loaded = {}
    for name in ('device_profiles', 'firmware'):
        spec = importlib.util.spec_from_file_location('passage_' + name, root / (name + '.py'))
        loaded[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded[name])
    registry = loaded['device_profiles']
    images = loaded['firmware']
    baseline = registry.registry(root / 'firmware.json')
    manifest_file = bundle_file(bundle, 'firmware.json')
    devices = registry.registry(manifest_file)
    def without_assets(profiles):
        return {name: {key: value for key, value in profile.items() if key != 'prebuilt'}
                for name, profile in profiles.items()}
    if without_assets(devices) != without_assets(baseline):
        raise ValueError('Firmware bundle changes the release-owned device registry or source pins')
    receipt_file = bundle_file(bundle, 'firmware-build.json')
    receipt = json.loads(receipt_file.read_text())
    if receipt.get('schema_version') != 1 or not isinstance(receipt.get('models'), dict):
        raise ValueError('Firmware build receipt is invalid')
    files = {'firmware.json': manifest_file}
    bundled_models = set()
    for model, profile in devices.items():
        if profile.get('prebuilt') is None:
            continue
        artifact = images.prebuilt_spec(profile)
        if not artifact.get('bundled_path'):
            raise ValueError('Generated firmware bundles must supply local application images')
        if receipt['models'].get(model) != artifact or receipt.get('source_commit') != profile['commit']:
            raise ValueError('Firmware receipt differs from pinned model metadata')
        image = bundle_file(bundle, artifact['bundled_path'])
        if image.name != profile['filename']:
            raise ValueError('Bundled application image filename differs from its model')
        images.verify(image.read_bytes(), profile)
        notice = bundle_file(bundle, artifact['license_notice'])
        if not notice.read_text().strip():
            raise ValueError('Empty firmware redistribution notice')
        files[artifact['bundled_path']] = image
        files[artifact['license_notice']] = notice
        bundled_models.add(model)
    if not bundled_models or set(receipt['models']) != bundled_models:
        raise ValueError('Firmware receipt contains missing or undeclared application images')
    if set(receipt.get('environments', [])) != {devices[model]['environment'] for model in bundled_models}:
        raise ValueError('Firmware receipt build environments differ from the packaged models')
    license_file = bundle_file(bundle, 'desktop/licenses/firmware/licenses.json')
    licenses = json.loads(license_file.read_text())
    if not isinstance(licenses, list) or not licenses:
        raise ValueError('Firmware dependency license inventory is missing')
    files['desktop/licenses/firmware/licenses.json'] = license_file
    for entry in licenses:
        if (not isinstance(entry, dict) or not isinstance(entry.get('file'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', entry.get('sha256', ''))):
            raise ValueError('Invalid firmware license inventory entry')
        name = 'desktop/licenses/firmware/' + entry['file']
        license_path = bundle_file(bundle, name)
        if file_digest(license_path) != entry['sha256']:
            raise ValueError('Firmware dependency license checksum mismatch')
        files[name] = license_path
    source = receipt.get('source_archive', {})
    if (source.get('filename') != 'passage-firmware-source.tar.gz'
            or not re.fullmatch(r'[a-f0-9]{64}', source.get('sha256', ''))
            or type(source.get('size')) is not int or source['size'] <= 0):
        raise ValueError('Corresponding firmware source receipt is missing')
    source_file = bundle_file(bundle, source['filename'])
    if source_file.stat().st_size != source['size'] or file_digest(source_file) != source['sha256']:
        raise ValueError('Corresponding firmware source checksum mismatch')
    return {'manifest': json.loads(manifest_file.read_text()), 'bridge_files': files,
            'source_files': {source['filename']: source_file, 'firmware-build.json': receipt_file},
            'receipt': receipt, 'file_hashes': {name: file_digest(path) for name, path in files.items()}}


def validate_identity(identity, keychain=None):
    if identity == '-':
        return
    command = ['security', 'find-identity', '-v', '-p', 'codesigning']
    if keychain:
        command.append(str(keychain))
    available = run(*command, capture_output=True, text=True).stdout
    identities = re.findall(r'([A-Fa-f0-9]{40})\s+"(Developer ID Application: [^"]+)"', available)
    if not any(identity == name or identity.upper() == digest.upper() for digest, name in identities):
        raise ValueError('A valid Developer ID Application identity is required; development/distribution certificates cannot sign a consumer Mac release')


def create_dmg(app, dmg, *, development=True):
    if dmg.exists():
        raise ValueError('Disk image destination already exists; choose a fresh output directory')
    with tempfile.TemporaryDirectory(prefix='passage-dmg-') as directory:
        install = Path(directory)
        shutil.copytree(app, install / app.name, symlinks=True)
        (install / 'Applications').symlink_to('/Applications')
        warning = 'Development build: not notarized for public distribution.\n' if development else ''
        source_note = ('Firmware source: Passage.app/Contents/Resources/firmware-source/.\n'
                       'Firmware notices: Passage.app/Contents/Resources/bridge/desktop/licenses/firmware/.\n'
                       if (app / 'Contents/Resources/firmware-source').is_dir() else
                       'This package does not include application firmware images.\n')
        (install / 'READ ME.txt').write_text(
            'Drag Passage to Applications, eject this disk image, then open Passage.\n'
            + warning + 'Choose the reader you use; a second reader is optional.\n'
            'Kindle requires a supported jailbreak and working KOReader.\n'
            'Xteink requires CrossPoint and the matching Passage firmware.\n'
            'See the included setup guide before changing reader software.\n' + source_note)
        run('hdiutil', 'create', '-volname', 'Passage', '-srcfolder', install, '-format', 'UDZO', dmg)


def runtime(cache, spec):
    archive = cache / (spec['sha256'] + '.tar.gz')
    cache.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        print('Downloading pinned Python runtime…', flush=True)
        temporary = archive.with_suffix('.download')
        try:
            # Apple's curl uses the system certificate trust store, unlike some
            # developer Python installations with an unconfigured CA bundle.
            run('/usr/bin/curl', '--fail', '--location', '--proto', '=https', '--proto-redir', '=https',
                '--connect-timeout', '30', '--max-time', '600', '--output', temporary, spec['url'])
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != spec['sha256']:
                raise RuntimeError('Python runtime checksum mismatch')
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != spec['sha256']:
        raise RuntimeError('Cached runtime checksum mismatch; remove only the invalid cache archive and retry')
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--dmg', action='store_true')
    parser.add_argument('--sign-identity', default='-', help='Developer ID Application identity; defaults to local ad-hoc signing')
    parser.add_argument('--keychain', type=Path, help='Optional dedicated signing keychain')
    parser.add_argument('--release-candidate', action='store_true', help='Require a clean committed source and Developer ID signature; does not establish notarization')
    parser.add_argument('--firmware-bundle', type=Path, help='Generated pinned firmware bundle with application images, source and dependency notices')
    args = parser.parse_args()
    if sys.platform != 'darwin' or not hasattr(tarfile, 'data_filter'):
        parser.error('Building requires macOS, Xcode command line tools, and Python 3.12 or newer')
    validate_identity(args.sign_identity, args.keychain)
    if args.release_candidate and args.sign_identity == '-':
        parser.error('Release candidates require Developer ID Application signing')
    source_status = run('git', '-C', ROOT, 'status', '--porcelain', capture_output=True, text=True).stdout.strip()
    if args.release_candidate and source_status:
        parser.error('Release candidates require a clean committed source tree')
    architecture = platform.machine()
    manifest = json.loads((ROOT / 'desktop/runtime.json').read_text())
    if architecture not in manifest['architectures']:
        parser.error('No pinned runtime is available for this architecture')
    spec = manifest['architectures'][architecture]
    release = release_settings()
    allowlist = resource_paths()
    assets = firmware_bundle(args.firmware_bundle) if args.firmware_bundle else None
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = output / 'Passage.app'
    if app.exists():
        parser.error(f'{app} already exists. Choose a fresh --output directory to preserve the previous build.')
    cache = ROOT / '.build-cache'
    archive = runtime(cache, spec)
    env = {**os.environ, 'MACOSX_DEPLOYMENT_TARGET': '13.0'}
    run('swift', 'build', '--package-path', ROOT / 'desktop', '-c', 'release', env=env)
    bin_path = run('swift', 'build', '--package-path', ROOT / 'desktop', '-c', 'release', '--show-bin-path', capture_output=True, text=True, env=env).stdout.strip()
    # Assemble separately so a failed build never masquerades as a complete app.
    with tempfile.TemporaryDirectory(prefix='passage-', dir=output) as temporary:
        staging = Path(temporary) / app.name
        contents = staging / 'Contents'
        resources = contents / 'Resources'
        executable_dir = contents / 'MacOS'
        executable_dir.mkdir(parents=True)
        resources.mkdir()
        shutil.copy2(Path(bin_path) / 'ReaderBridge', executable_dir / 'ReaderBridge')
        with tarfile.open(archive) as source:
            source.extractall(resources, filter='data')
        (resources / 'python').rename(resources / 'runtime')
        bridge = resources / 'bridge'
        bridge.mkdir()
        for relative in allowlist['bridge_files']:
            destination = bridge / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        for relative in allowlist['documentation_files']:
            destination = resources / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        if assets:
            for name, source in assets['bridge_files'].items():
                destination = bridge / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            for name, source in assets['source_files'].items():
                destination = resources / 'firmware-source' / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        shutil.copy2(ROOT / 'desktop/resources.json', resources / 'resources.json')
        for relative in allowlist['runtime_license_files']:
            destination = resources / 'licenses' / relative.relative_to('desktop/licenses')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        shutil.copy2(ROOT / 'desktop/THIRD-PARTY-NOTICES.md', resources / 'THIRD-PARTY-NOTICES.md')
        icon_renderer = Path(temporary) / 'make-icon'
        run('swiftc', ROOT / 'desktop/Sources/ReaderBridge/BrandMarkGeometry.swift',
            ROOT / 'scripts/make-icon.swift', '-o', icon_renderer)
        run(icon_renderer, resources / 'ReaderBridge.icns')
        info = {
            'CFBundleName': 'Passage', 'CFBundleDisplayName': 'Passage',
            # Keep the existing identity: settings, login items and reader pairing survive upgrades.
            'CFBundleIdentifier': release['bundle_identifier'], 'CFBundleExecutable': 'ReaderBridge',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': release['version'],
            'CFBundleVersion': release['build'], 'LSMinimumSystemVersion': release['minimum_macos'],
            'CFBundleIconFile': 'ReaderBridge', 'NSHighResolutionCapable': True,
            'NSLocalNetworkUsageDescription': 'Passage pairs your readers and syncs their highlights and reading positions on your home network.',
            'NSRemovableVolumesUsageDescription': 'Passage installs its plugin and pairing settings on the reader you choose.',
        }
        (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
        revision = run('git', '-C', ROOT, 'rev-parse', 'HEAD', capture_output=True, text=True).stdout.strip()
        (resources / 'build.json').write_text(json.dumps({
            'schema_version': 1, 'commit': revision, 'source_dirty': bool(source_status),
            'architecture': architecture, 'version': release['version'], 'build': release['build'],
            'runtime': manifest, 'firmware': assets['manifest'] if assets else json.loads((ROOT / 'firmware.json').read_text()),
            'firmware_assets': assets['file_hashes'] if assets else {},
            'firmware_source': assets['receipt']['source_archive'] if assets else None,
            'signing': 'ad-hoc' if args.sign_identity == '-' else 'Developer ID',
            'distribution': 'release-candidate' if args.release_candidate else 'development',
        }, indent=2) + '\n')
        # Sign Mach-O files inside out, including the runtime's native modules.
        sign_options = ['--force', '--sign', args.sign_identity]
        if args.sign_identity != '-':
            sign_options += ['--timestamp', '--options', 'runtime']
        if args.keychain:
            sign_options += ['--keychain', str(args.keychain)]
        for path in sorted(staging.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            if path.is_symlink() or not path.is_file():
                continue
            with path.open('rb') as file:
                is_native = file.read(4) in MACHO
            if is_native:
                run('codesign', *sign_options, path, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        run('codesign', *sign_options, staging)
        run('codesign', '--verify', '--deep', '--strict', staging)
        # Prove the packaged runtime/helper works without relying on host Python.
        isolated_data = Path(temporary) / 'smoke-data'
        smoke = run(resources / 'runtime/bin/python3', '-E', '-s', '-B', bridge / 'desktop.py', '--app-dir', isolated_data,
                    input='{"command":"status"}', capture_output=True, text=True)
        response = json.loads(smoke.stdout)
        if not response.get('ok') or isolated_data.exists():
            raise RuntimeError('Bundled status smoke failed or created data during read-only startup')
        run(resources / 'runtime/bin/python3', '-I', '-B', '-c',
            'import ctypes, hashlib, sqlite3, ssl, zlib; assert ssl.OPENSSL_VERSION; assert sqlite3.connect(":memory:").execute("SELECT 1").fetchone() == (1,)')
        run('codesign', '--verify', '--deep', '--strict', staging)
        staging.rename(app)
    if args.dmg:
        dmg = output / f'Passage-{info["CFBundleShortVersionString"]}-{architecture}-development.dmg'
        create_dmg(app, dmg)
        digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
        dmg.with_suffix('.dmg.sha256').write_text(f'{digest}  {dmg.name}\n')
    print(f'Built {app}')
    print('Local development build. Public distribution requires Developer ID signing and Apple notarization.' if args.sign_identity == '-' else 'Signed build. Notarize and staple before public distribution.')


if __name__ == '__main__':
    main()
