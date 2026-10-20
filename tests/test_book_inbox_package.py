import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('book_inbox_package', ROOT / 'scripts/package-book-inbox.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class InboxPackageTests(unittest.TestCase):
    def test_release_archive_is_reproducible_and_runs_without_checkout_or_private_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            for name in builder.FILES:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            subprocess.run(['git', 'add', '.'], cwd=source, check=True)
            subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                            'commit', '-qm', 'Synthetic release fixture'], cwd=source, check=True)
            # Even ignored private files must never become distributed assets.
            (source / '.git/info/exclude').write_text('config.json\n')
            (source / 'config.json').write_text('{"token": "private-fixture"}')
            first = builder.package(root / 'first', source)
            second = builder.package(root / 'second', source)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            extracted = root / 'extracted'
            with tarfile.open(first) as archive:
                for entry in archive.getmembers():
                    self.assertTrue(entry.isfile())
                    self.assertNotIn('..', Path(entry.name).parts)
                archive.extractall(extracted)
            folder = extracted / ('passage-book-inbox-' + builder.VERSION)
            manifest = json.loads((folder / 'release.json').read_text())
            self.assertFalse(manifest['packaged_mac_app'])
            self.assertFalse((folder / 'config.json').exists())
            for name, details in manifest['files'].items():
                data = (folder / name).read_bytes()
                self.assertEqual(len(data), details['size'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), details['sha256'])
            subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests'],
                           cwd=folder, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (source / 'book_sync.py').write_text('# modified source')
            with self.assertRaisesRegex(ValueError, 'clean committed'):
                builder.package(root / 'dirty', source)


if __name__ == '__main__':
    unittest.main()
