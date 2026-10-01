#!/usr/bin/env python3
"""Build a self-contained Reader Bridge.app; no Python required on the user's Mac."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MACHO = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xfe\xed\xfa\xce', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


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
    args = parser.parse_args()
    if sys.platform != 'darwin' or not hasattr(tarfile, 'data_filter'):
        parser.error('Building requires macOS, Xcode command line tools, and Python 3.12 or newer')
    architecture = platform.machine()
    manifest = json.loads((ROOT / 'desktop/runtime.json').read_text())
    spec = manifest['architectures'][architecture]
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = output / 'Reader Bridge.app'
    if app.exists():
        parser.error(f'{app} already exists. Choose a fresh --output directory to preserve the previous build.')
    cache = ROOT / '.build-cache'
    archive = runtime(cache, spec)
    env = {**os.environ, 'MACOSX_DEPLOYMENT_TARGET': '13.0'}
    run('swift', 'build', '--package-path', ROOT / 'desktop', '-c', 'release', env=env)
    bin_path = run('swift', 'build', '--package-path', ROOT / 'desktop', '-c', 'release', '--show-bin-path', capture_output=True, text=True, env=env).stdout.strip()
    # Assemble separately so a failed build never masquerades as a complete app.
    with tempfile.TemporaryDirectory(prefix='reader-bridge-', dir=output) as temporary:
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
        for filename in ('desktop.py', 'setup.py', 'collector.py', 'db.py', 'import_clippings.py', 'firmware.json', 'LICENSE'):
            shutil.copy2(ROOT / filename, bridge / filename)
        shutil.copytree(ROOT / 'koreader', bridge / 'koreader', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'tests'))
        shutil.copytree(ROOT / 'docs', resources / 'docs')
        shutil.copy2(ROOT / 'README.md', resources / 'README.md')
        shutil.copytree(ROOT / 'desktop/licenses', resources / 'licenses')
        shutil.copy2(ROOT / 'desktop/THIRD-PARTY-NOTICES.md', resources / 'THIRD-PARTY-NOTICES.md')
        run('swift', ROOT / 'scripts/make-icon.swift', resources / 'ReaderBridge.icns')
        info = {
            'CFBundleName': 'Reader Bridge', 'CFBundleDisplayName': 'Reader Bridge',
            'CFBundleIdentifier': 'com.readerbridge.desktop', 'CFBundleExecutable': 'ReaderBridge',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '0.3.1',
            'CFBundleVersion': '5', 'LSMinimumSystemVersion': '13.0',
            'CFBundleIconFile': 'ReaderBridge', 'NSHighResolutionCapable': True,
            'NSLocalNetworkUsageDescription': 'Reader Bridge pairs your readers and receives their highlights on your home network.',
            'NSRemovableVolumesUsageDescription': 'Reader Bridge installs its plugin and pairing settings on the reader you choose.',
        }
        (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
        revision = run('git', '-C', ROOT, 'rev-parse', 'HEAD', capture_output=True, text=True).stdout.strip()
        (resources / 'build.json').write_text(json.dumps({'commit': revision, 'architecture': architecture, 'runtime': manifest, 'signing': 'ad-hoc' if args.sign_identity == '-' else 'Developer ID'}, indent=2) + '\n')
        # Sign Mach-O files inside out, including the runtime's native modules.
        sign_options = ['--force', '--sign', args.sign_identity]
        if args.sign_identity != '-':
            sign_options += ['--timestamp', '--options', 'runtime']
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
        staging.rename(app)
    if args.dmg:
        dmg = output / f'Reader-Bridge-0.3.1-{architecture}.dmg'
        if dmg.exists():
            parser.error('DMG destination exists; choose a fresh output directory')
        with tempfile.TemporaryDirectory(prefix='reader-bridge-dmg-') as directory:
            install = Path(directory)
            shutil.copytree(app, install / app.name, symlinks=True)
            (install / 'Applications').symlink_to('/Applications')
            distribution = 'This development build is not notarized for public distribution.\n' if args.sign_identity == '-' else 'See the release notes for notarization and compatibility status.\n'
            (install / 'READ ME.txt').write_text('Drag Reader Bridge to Applications, then open it.\n' + distribution + 'Kindle jailbreaking and KOReader installation remain prerequisites.\n')
            run('hdiutil', 'create', '-volname', 'Reader Bridge', '-srcfolder', install, '-format', 'UDZO', dmg)
        digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
        dmg.with_suffix('.dmg.sha256').write_text(f'{digest}  {dmg.name}\n')
    print(f'Built {app}')
    print('Local development build. Public distribution requires Developer ID signing and Apple notarization.' if args.sign_identity == '-' else 'Signed build. Notarize and staple before public distribution.')


if __name__ == '__main__':
    main()
