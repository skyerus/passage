#!/usr/bin/env python3
"""Run bundled-runtime acceptance in an empty, disposable namespace.

This is automated package acceptance on the current OS, not proof of a clean
Mac, Gatekeeper's first-open UI, an actual login, or physical-reader behavior.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Packaged acceptance requires macOS with a logged-in GUI session')
    app = args.app.expanduser().resolve()
    if not app.is_dir() or app.name != 'Passage.app':
        parser.error('Choose a packaged Passage.app; existing installations are never modified')
    runtime = app / 'Contents/Resources/runtime/bin/python3'
    if Path(sys.executable).resolve() != runtime.resolve() or not sys.dont_write_bytecode:
        parser.error('Run this script with the app’s runtime and -I -B')
    if args.report.exists():
        parser.error('Report exists; choose a fresh report path')
    build = json.loads((app / 'Contents/Resources/build.json').read_text())
    with tempfile.TemporaryDirectory(prefix='passage-clean-namespace-') as temporary:
        root = Path(temporary).resolve()
        home = root / 'home'
        home.mkdir()
        tools = root / 'system-tools'
        tools.mkdir()
        # Apple's Git/Python stubs are deliberately absent, along with Homebrew.
        for name, source in {'launchctl': '/bin/launchctl', 'plutil': '/usr/bin/plutil',
                             'codesign': '/usr/bin/codesign'}.items():
            (tools / name).symlink_to(source)
        environment = {'PASSAGE_ACCEPTANCE_HOME': str(home), 'PATH': str(tools), 'TMPDIR': str(root),
                       'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1',
                       'LANG': 'en_US.UTF-8'}
        for name in ('__CF_USER_TEXT_ENCODING', 'SECURITYSESSIONID'):
            if name in os.environ:
                environment[name] = os.environ[name]
        for name in ('git', 'gh', 'python3', 'pip', 'pio', 'swift', 'xcodebuild', 'clang'):
            if shutil.which(name, path=environment['PATH']):
                raise RuntimeError('Developer command leaked into the acceptance environment')
        subprocess.run([str(runtime), '-I', '-B', str(ROOT / 'scripts/smoke-macos.py'), str(app)],
                       env=environment, check=True)
        if list(home.rglob('*')):
            raise RuntimeError('Acceptance unexpectedly wrote outside its explicit test data')
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({
        'schema_version': 1, 'scope': 'isolated-data-and-service-namespace', 'passed': True,
        'tested_at': datetime.now(timezone.utc).isoformat(), 'commit': build['commit'],
        'version': build['version'], 'architecture': build['architecture'],
        'macos_version': platform.mac_ver()[0],
        'developer_commands_on_path': False, 'host_python_used': False,
        'real_user_data_used': False, 'real_reader_used': False,
        'checks': ['bundled_native_modules', 'read_only_first_status', 'local_collector',
                   'idempotent_install', 'occupied_port', 'upload_restart_token_retention',
                   'cover_export', 'folder_backup_restore_deletions', 'fixture_pairing_queues',
                   'progress_http_conflict_restart', 'owned_services_cleanup', 'signature_retained'],
        'limitations': ['Existing macOS and GUI login session; not a clean operating system.',
                        'Services are real launchd jobs in random test labels; their configured PATH is checked separately.',
                        'Physical reader, native first-open UI, logout/login, iCloud delivery and sleep acceptance are separate.'],
    }, indent=2) + '\n')
    print('PASS: isolated package acceptance. Clean-OS and physical-reader acceptance remain separate.')


if __name__ == '__main__':
    main()
