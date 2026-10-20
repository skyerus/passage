#!/usr/bin/env python3
"""Package the optional source-installed inbox; never includes personal state."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.0-rc.1'
FILES = (
    'LICENSE', 'book_sync.py', 'docs/BOOK-SYNC.md',
    'koreader/bookinbox.koplugin/_meta.lua',
    'koreader/bookinbox.koplugin/main.lua',
    'koreader/bookinbox.koplugin/sync.lua',
    'koreader/bookinbox.koplugin/tests/sync_test.lua',
    'koreader/bookinbox.koplugin/tests/transfer_test.lua',
    'tests/test_book_sync.py',
)
README = """# Passage Kindle Book Inbox {version}

This is an experimental source add-on requiring manual setup, Python 3.10+,
Calibre with KFX Input, a jailbroken Kindle with KOReader, and a separately
installed compatible export tool. It is separate from the Passage Mac app.
No runtime, books, credentials, export/decryption tools or firmware are bundled.

Read docs/BOOK-SYNC.md for prerequisites, pairing, startup, recovery and limits.
Keep the extracted folder layout; the guide's paths refer to this folder.
Follow its setup steps to copy book_sync.py into a new private service directory
and koreader/bookinbox.koplugin into the reader's koreader/plugins directory.
Amazon's native purchase download is still required. Xteink automatic delivery
is not implemented. Do not replace existing pairing files or service state.

release.json records the exact source commit and SHA-256 of every included file.
The archive's separate .sha256 file verifies the download before extraction.
To run the synthetic checks from this folder:

    python3 -m unittest discover -s tests -v
    for test in koreader/bookinbox.koplugin/tests/*_test.lua; do lua "$test"; done

The Lua checks use Lua 5.1. See LICENSE for the add-on's MIT license.
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def package(output, root=ROOT):
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('A full source commit is required')
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=root):
        raise ValueError('Package only a clean committed source tree')
    # Read an explicit allowlist from Git, never from a private runtime directory.
    contents = {name: subprocess.check_output(['git', 'show', commit + ':' + name], cwd=root)
                for name in FILES}
    contents['README.md'] = README.format(version=VERSION).encode()
    manifest = dict(schema_version=1, version=VERSION, commit=commit,
                    distribution='experimental-source-addon', packaged_mac_app=False,
                    files={name: dict(size=len(data), sha256=digest(data))
                           for name, data in sorted(contents.items())})
    contents['release.json'] = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    stem = 'passage-book-inbox-' + VERSION
    archive = output / (stem + '.tar.gz')
    if archive.exists() or archive.with_name(archive.name + '.sha256').exists():
        raise ValueError('Choose a fresh output directory; release assets are never replaced')
    # Fixed metadata makes the archive reproducible from the same commit.
    with archive.open('xb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as bundle:
                for name, data in sorted(contents.items()):
                    entry = tarfile.TarInfo(stem + '/' + name)
                    entry.size, entry.mode = len(data), 0o644
                    bundle.addfile(entry, io.BytesIO(data))
    checksum = digest(archive.read_bytes())
    archive.with_name(archive.name + '.sha256').write_text(checksum + '  ' + archive.name + '\n')
    print(json.dumps(dict(archive=str(archive), sha256=checksum, commit=commit)))
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    package(parser.parse_args().output)
