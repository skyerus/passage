#!/usr/bin/env python3
"""Prepare a notarized Passage candidate; finalize only after clean-Mac acceptance.

This script never publishes assets, changes Gatekeeper policy, imports keys, or
modifies an existing application or service. Credentials stay in a caller-owned
keychain profile. See docs/RELEASING.md.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CHECKS = ('download_install_open', 'no_developer_tools', 'collector_login_restart',
          'offline_reconnect', 'port_conflict', 'backup_restore', 'upgrade_runtime_path')


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def digest(path):
    with Path(path).open('rb') as source:
        result = hashlib.sha256()
        for block in iter(lambda: source.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def module(path):
    spec = importlib.util.spec_from_file_location('passage_builder', path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def signature(app):
    run('codesign', '--verify', '--deep', '--strict', app, capture_output=True)
    result = run('codesign', '--display', '--verbose=4', app, capture_output=True, text=True)
    details = result.stdout + result.stderr
    if ('Authority=Developer ID Application:' not in details
            or not re.search(r'flags=.*\bruntime\b', details) or 'Timestamp=' not in details):
        raise ValueError('App lacks Developer ID Application, hardened runtime, or secure timestamp')
    entitlements = run('codesign', '--display', '--entitlements', ':-', app, capture_output=True).stdout
    if entitlements and plistlib.loads(entitlements).get('com.apple.security.get-task-allow'):
        raise ValueError('Debug entitlement is forbidden in a public release')
    team = re.search(r'^TeamIdentifier=(\w+)$', details, re.MULTILINE)
    if not team or team.group(1) == 'not':
        raise ValueError('Signed application has no team identifier')
    cdhash = re.search(r'^CDHash=([a-f0-9]+)$', details, re.MULTILINE)
    if not cdhash:
        raise ValueError('Signed application has no code-directory hash')
    return {'team_identifier': team.group(1), 'cdhash': cdhash.group(1),
            'hardened_runtime': True, 'secure_timestamp': True}


def notarize(artifact, profile, report, keychain=None, staple_target=None):
    credentials = ['--keychain-profile', profile]
    if keychain:
        credentials += ['--keychain', str(keychain)]
    response = run('xcrun', 'notarytool', 'submit', artifact, *credentials,
                   '--wait', '--timeout', '20m', '--output-format', 'json',
                   capture_output=True, text=True)
    status = json.loads(response.stdout)
    write_json(report, status)
    if not status.get('id'):
        raise ValueError('Notary response contains no submission ID')
    run('xcrun', 'notarytool', 'log', status['id'], *credentials,
        report.with_suffix('.log.json'), capture_output=True)
    if status.get('status') != 'Accepted':
        raise ValueError('Apple did not accept this submission; inspect the saved notary log')
    target = staple_target or artifact
    run('xcrun', 'stapler', 'staple', target, capture_output=True)
    run('xcrun', 'stapler', 'validate', target, capture_output=True)
    return {'id': status['id'], 'status': 'Accepted', 'stapled': True}


def assess(app, dmg=None):
    signature(app)
    run('xcrun', 'stapler', 'validate', app, capture_output=True)
    run('spctl', '--assess', '--type', 'execute', '--verbose=4', app, capture_output=True)
    if dmg:
        run('codesign', '--verify', '--strict', dmg, capture_output=True)
        run('xcrun', 'stapler', 'validate', dmg, capture_output=True)
        run('spctl', '--assess', '--type', 'open', '--context', 'context:primary-signature',
            '--verbose=4', dmg, capture_output=True)


@contextmanager
def installed_from_dmg(artifact):
    """Copy the disk image's application into a disposable install location."""
    with tempfile.TemporaryDirectory(prefix='passage-release-install-') as temporary:
        root = Path(temporary)
        mounted = root / 'mount'
        mounted.mkdir()
        run('hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen', '-mountpoint', mounted, artifact,
            capture_output=True)
        try:
            if not (mounted / 'Applications').is_symlink() or (mounted / 'Applications').readlink() != Path('/Applications'):
                raise ValueError('Installer Applications link is invalid')
            installed = root / 'Applications/Passage.app'
            run('ditto', mounted / 'Passage.app', installed)
        finally:
            run('hdiutil', 'detach', mounted, capture_output=True)
        yield installed


def validate_acceptance(candidate, acceptance):
    if acceptance.get('schema_version') != 1 or acceptance.get('scope') != 'clean-mac-without-developer-tools':
        raise ValueError('A separate clean-Mac acceptance report is required')
    for field in ('commit', 'version', 'architecture', 'artifact_sha256'):
        expected = candidate['artifact']['sha256'] if field == 'artifact_sha256' else candidate[field]
        if acceptance.get(field) != expected:
            raise ValueError('Acceptance does not match this candidate: ' + field)
    if not acceptance.get('macos_version') or not acceptance.get('tested_at'):
        raise ValueError('Acceptance needs the tested OS version and date')
    checks = acceptance.get('checks', {})
    for name in CHECKS:
        check = checks.get(name, {})
        if not isinstance(check, dict) or check.get('passed') is not True or not check.get('evidence'):
            raise ValueError('Missing physical acceptance evidence: ' + name)
    readers = acceptance.get('readers', [])
    if not isinstance(readers, list) or not readers:
        raise ValueError('Record at least one physically accepted reader')
    supported = {profile['id']: profile for profile in candidate.get('reader_profiles', [])}
    accepted = set()
    for reader in readers:
        identity = reader.get('profile_id') if isinstance(reader, dict) else None
        profile = supported.get(identity)
        if not profile or identity in accepted or reader.get('passed') is not True or not reader.get('evidence'):
            raise ValueError('Unknown, duplicate, or untested reader profile')
        if profile.get('kind') != 'kindle' and not profile.get('prebuilt_ready'):
            raise ValueError('Accepted CrossPoint profile lacks a verified prebuilt with packaged source and notices')
        accepted.add(identity)
    if len(accepted) > 1:
        check = checks.get('progress_roundtrip', {})
        if check.get('passed') is not True or not check.get('evidence'):
            raise ValueError('Multiple-reader release requires a physical progress round trip')
    return sorted(accepted)


def finalize(path, acceptance_path):
    candidate = json.loads(path.read_text())
    if (candidate.get('schema_version') != 1 or candidate.get('state') != 'notarized-candidate'
            or candidate.get('automated_acceptance', {}).get('passed') is not True
            or candidate.get('automated_acceptance', {}).get('scope') != 'isolated-data-and-service-namespace'
            or candidate.get('notarization', {}).get('app', {}).get('status') != 'Accepted'
            or candidate.get('notarization', {}).get('dmg', {}).get('status') != 'Accepted'):
        raise ValueError('A successfully verified notarized candidate is required')
    artifact = path.parent / candidate['artifact']['filename']
    if artifact.parent.resolve() != path.parent.resolve() or digest(artifact) != candidate['artifact']['sha256']:
        raise ValueError('Candidate disk image changed or is missing')
    acceptance = json.loads(acceptance_path.read_text())
    with installed_from_dmg(artifact) as app:
        build = json.loads((app / 'Contents/Resources/build.json').read_text())
        for field in ('commit', 'version', 'architecture'):
            if candidate.get(field) != build.get(field):
                raise ValueError('Candidate differs from the signed app: ' + field)
            if candidate['automated_acceptance'].get(field) != build.get(field):
                raise ValueError('Automated acceptance differs from the signed app: ' + field)
        if build.get('source_dirty') or build.get('distribution') != 'release-candidate':
            raise ValueError('Finalization requires a clean committed release build')
        if candidate.get('reader_profiles') != profiles(build):
            raise ValueError('Candidate reader availability differs from the signed app')
        if candidate.get('firmware_source') != build.get('firmware_source'):
            raise ValueError('Candidate firmware source differs from the signed app')
        accepted = validate_acceptance(candidate, acceptance)
        assess(app, artifact)
        if signature(app) != candidate.get('signing'):
            raise ValueError('Signed candidate changed after automated acceptance')
        source = candidate.get('firmware_source')
        if source:
            source_file = path.parent / source['filename']
            if source_file.parent.resolve() != path.parent.resolve() or digest(source_file) != source['sha256']:
                raise ValueError('Corresponding firmware source release asset changed or is missing')
    candidate.update(state='distribution-ready', ready=True, accepted_reader_profiles=accepted,
                     clean_mac_acceptance=acceptance, blockers=[])
    write_json(path.parent / 'release-manifest.json', candidate)
    print('Distribution verified for ' + ', '.join(accepted) + '. No assets were published.')


def profiles(build):
    values = build.get('firmware', {}).get('devices', {})
    result = [{'id': 'kindle', 'kind': 'kindle', 'prebuilt_ready': True}]
    assets = build.get('firmware_assets', {})
    for identity, profile in values.items():
        if not isinstance(profile, dict):
            raise ValueError('Invalid firmware profile')
        prebuilt = profile.get('prebuilt')
        ready = bool(isinstance(prebuilt, dict) and re.fullmatch(r'[a-f0-9]{64}', prebuilt.get('sha256', ''))
                     and prebuilt.get('size') and prebuilt.get('license_notice')
                     and prebuilt.get('commit') == profile.get('commit')
                     and prebuilt.get('model') == identity and prebuilt.get('environment') == profile.get('environment')
                     and assets.get(prebuilt.get('bundled_path')) == prebuilt.get('sha256')
                     and prebuilt.get('license_notice') in assets and build.get('firmware_source')
                     and profile.get('pairing_supported') is True)
        result.append({'id': identity, 'kind': 'crosspoint', 'prebuilt_ready': ready})
    return result


def prepare(args):
    builder = module(ROOT / 'scripts/build-macos.py')
    builder.validate_identity(args.sign_identity, args.keychain)
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose a fresh output directory; previous candidates are never replaced')
    command = [sys.executable, ROOT / 'scripts/build-macos.py', '--output', output,
               '--sign-identity', args.sign_identity, '--release-candidate']
    if args.keychain:
        command += ['--keychain', args.keychain]
    if args.firmware_bundle:
        command += ['--firmware-bundle', args.firmware_bundle]
    run(*command)
    app = output / 'Passage.app'
    build = json.loads((app / 'Contents/Resources/build.json').read_text())
    signed = signature(app)
    archive = output / 'notary-app.zip'
    run('ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', app, archive)
    app_notary = notarize(archive, args.notary_profile, output / 'notary-app.json', args.keychain, staple_target=app)
    # The ZIP cannot carry a stapled ticket. Attach and validate it on the app.
    assess(app)
    archive.unlink()
    dmg = output / f'Passage-{build["version"]}-{build["architecture"]}.dmg'
    builder.create_dmg(app, dmg, development=False)
    sign = ['codesign', '--force', '--sign', args.sign_identity, '--timestamp',
            '--identifier', 'com.readerbridge.desktop.diskimage']
    if args.keychain:
        sign += ['--keychain', args.keychain]
    run(*sign, dmg, capture_output=True)
    dmg_notary = notarize(dmg, args.notary_profile, output / 'notary-dmg.json', args.keychain)
    assess(app, dmg)
    # Exercise the copy users install from the actual signed disk image.
    with installed_from_dmg(dmg) as installed:
        run('xattr', '-w', 'com.apple.quarantine', '0083;00000000;PassageAcceptance;', installed)
        assess(installed)
        run(installed / 'Contents/Resources/runtime/bin/python3', '-I', '-B',
            ROOT / 'scripts/acceptance-macos.py', installed, '--report', output / 'automated-acceptance.json')
        assess(installed)
    checksum = digest(dmg)
    dmg.with_suffix('.dmg.sha256').write_text(f'{checksum}  {dmg.name}\n')
    source = build.get('firmware_source')
    if source:
        archive = app / 'Contents/Resources/firmware-source' / source['filename']
        if archive.stat().st_size != source['size'] or digest(archive) != source['sha256']:
            raise ValueError('Packaged corresponding firmware source changed')
        shutil.copy2(archive, output / source['filename'])
        (output / (source['filename'] + '.sha256')).write_text(f'{source["sha256"]}  {source["filename"]}\n')
    record = {'schema_version': 1, 'state': 'notarized-candidate', 'ready': False,
              'created_at': datetime.now(timezone.utc).isoformat(),
              'commit': build['commit'], 'version': build['version'], 'architecture': build['architecture'],
              'artifact': {'filename': dmg.name, 'sha256': checksum}, 'signing': signed,
              'firmware_source': source,
              'notarization': {'app': app_notary, 'dmg': dmg_notary},
              'automated_acceptance': json.loads((output / 'automated-acceptance.json').read_text()),
              'reader_profiles': profiles(build),
              'blockers': ['Separate clean-Mac and physical-reader acceptance has not been recorded.']}
    write_json(output / 'release-candidate.json', record)
    print(f'Notarized candidate: {dmg}. Test this exact download on a clean Mac, then finalize. No assets were published.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--sign-identity')
    parser.add_argument('--notary-profile', help='Existing notarytool keychain profile; no credentials in arguments')
    parser.add_argument('--keychain', type=Path)
    parser.add_argument('--firmware-bundle', type=Path, help='Verified generated firmware bundle; no binaries need to be committed')
    parser.add_argument('--finalize', type=Path, help='Existing release-candidate.json')
    parser.add_argument('--acceptance', type=Path, help='Exact-artifact clean-Mac and physical-device report')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Release verification requires macOS')
    if args.finalize:
        if not args.acceptance or args.output or args.sign_identity or args.notary_profile:
            parser.error('--finalize requires --acceptance and cannot build or sign a new candidate')
        finalize(args.finalize.resolve(), args.acceptance.resolve())
    else:
        if not args.output or not args.sign_identity or args.sign_identity == '-' or not args.notary_profile or args.acceptance:
            parser.error('Preparing a candidate requires --output, --sign-identity, and --notary-profile')
        prepare(args)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        # Command arguments can include a profile name; do not echo whole commands.
        print('Release stopped: ' + (str(error) if isinstance(error, ValueError) else 'a required build, signing, notarization, or verification step failed.'), file=sys.stderr)
        sys.exit(1)
