import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import archive_backup as backup
from collector import Store, initialize, item_key
import desktop
import setup


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.app = self.root / 'app'
        self.data, self.token = initialize(self.app / 'collector/data')
        self.store = Store(self.data / 'inbox.sqlite3')
        self.destination = self.root / 'cloud'
        self.destination.mkdir()
        self.worker = self.app / 'cloud_backup'
        self.item = {'id':'one', 'book_title':'Test Book', 'author':'Writer', 'text':'An original test quote', 'created_at':'2026-10-01T12:39:00', 'note':'a note'}
        self.batch = {'source':'crosspoint', 'device_id':'test-reader', 'highlights':[self.item]}
        self.store.accept(self.batch)

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        return backup.snapshot(self.store.path, self.app, self.destination, self.worker)

    def test_snapshot_preserves_dates_notes_and_omits_credentials(self):
        (self.data / 'credentials.json').write_text('SECRET_NOT_FOR_BACKUP')
        receipt = self.save()
        manifest, _ = backup.read_snapshot(receipt['path'])
        self.assertEqual(manifest['records'], [self.batch])
        with zipfile.ZipFile(receipt['path']) as z:
            self.assertEqual(z.namelist(), ['archive.json'])
            raw = z.read('archive.json')
        self.assertNotIn(self.token.encode(), raw)
        self.assertNotIn(b'SECRET_NOT_FOR_BACKUP', raw)
        self.assertFalse(receipt['cloud_upload_verified'])

    def test_no_duplicate_snapshot_for_publication_ack_but_deletion_versions(self):
        first = self.save()
        self.store.acknowledge(self.store.pending())
        self.assertEqual(first['path'], self.save()['path'])
        self.store.accept({**self.batch, 'highlights':[{'id':'one','deleted':True}]})
        second = self.save()
        self.assertNotEqual(first['path'], second['path'])
        self.assertTrue(Path(first['path']).is_file())
        manifest, _ = backup.read_snapshot(second['path'])
        self.assertIn(item_key(self.item), manifest['tombstones'])

    def test_restore_into_fresh_database_and_undated_replay(self):
        first = self.save()
        new_app = self.root / 'new'
        data, token = initialize(new_app / 'collector/data')
        store = Store(data / 'inbox.sqlite3')
        backup.restore(first['path'], store.path, new_app)
        copied = json.loads(store.pending()[0][3])
        self.assertEqual(copied, self.item)
        self.assertNotEqual(token, self.token)
        replay = dict(self.item)
        replay.pop('created_at')
        store.accept({**self.batch, 'highlights':[replay]})
        self.assertEqual(json.loads(store.pending()[0][3])['created_at'], self.item['created_at'])
        self.assertEqual(len(list((new_app / 'backups/before-restore').glob('*.readerbridge'))), 1)

    def test_restore_preserves_current_edits_and_never_resurrects_deletion(self):
        old = self.save()
        edited = dict(self.item, text='Newer edited passage', note='new note')
        self.store.accept({**self.batch, 'highlights':[edited]})
        backup.restore(old['path'], self.store.path, self.app)
        self.assertEqual(json.loads(self.store.pending()[0][3]), edited)
        self.store.accept({**self.batch, 'highlights':[{'id':'one','deleted':True}]})
        backup.restore(old['path'], self.store.path, self.app)
        self.assertTrue(json.loads(self.store.pending()[0][3])['deleted'])
        self.store.accept({**self.batch, 'highlights':[dict(self.item, id='replay')]})
        self.assertTrue(all(json.loads(r[3]).get('deleted') for r in self.store.pending()))

    def test_cover_bytes_and_mapping_survive_restore(self):
        image = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXioAAAAASUVORK5CYII=')
        digest = hashlib.sha256(image).hexdigest()
        key = 'a' * 64
        (self.data / 'covers').mkdir()
        (self.data / 'covers' / (digest + '.png')).write_bytes(image)
        with self.store.connect() as con:
            con.execute('CREATE TABLE book_covers(book_key TEXT PRIMARY KEY, sha256 TEXT, extension TEXT)')
            con.execute('INSERT INTO book_covers VALUES(?,?,?)', (key,digest,'png'))
        saved = self.save()
        new_app = self.root / 'new'
        data, _ = initialize(new_app / 'collector/data')
        store = Store(data / 'inbox.sqlite3')
        backup.restore(saved['path'], store.path, new_app)
        self.assertEqual((data / 'covers' / (digest + '.png')).read_bytes(), image)
        with store.connect() as con:
            self.assertEqual(con.execute('SELECT * FROM book_covers').fetchone(), (key,digest,'png'))

    def test_missing_folder_keeps_previous_snapshot_and_worker_retries(self):
        saved = self.save()
        moved = self.root / 'offline'
        self.destination.rename(moved)
        config = {'database':self.store.path,'app':str(self.app),'destination':str(self.destination)}
        failed = backup.run_once(config, self.worker)
        self.assertIn('error', failed)
        self.assertFalse(self.destination.exists())
        moved.rename(self.destination)
        good = backup.run_once(config, self.worker)
        self.assertNotIn('error', good)
        self.assertEqual(saved['path'], good['path'])

    def test_corrupt_cover_and_traversal_fail_before_database_mutation(self):
        original = Path(self.save()['path'])
        bad = self.root / 'bad.readerbridge'
        with zipfile.ZipFile(original) as z, zipfile.ZipFile(bad, 'w') as out:
            out.writestr('archive.json', z.read('archive.json'))
            out.writestr('../token', b'bad')
        before = self.store.pending()
        with self.assertRaises(ValueError):
            backup.restore(bad, self.store.path, self.app)
        self.assertEqual(self.store.pending(), before)
        link = self.root / 'link'
        link.symlink_to(self.destination, target_is_directory=True)
        with self.assertRaises(ValueError):
            backup.snapshot(self.store.path, self.app, link, self.worker)

    def test_icloud_requires_real_icloud_folder_and_keeps_github_configuration(self):
        bridge = desktop.Desktop(self.app, agent_dir=self.root / 'agents')
        bridge.state['collector'] = {'archive':'reader/private','port':8084}
        with patch.object(desktop.sys, 'platform', 'darwin'), patch.object(bridge, 'assert_ownership'), patch.object(bridge, 'assert_loaded_ownership'), patch.object(bridge, 'stop_owned'), patch.object(bridge, 'launch') as launch:
            with self.assertRaises(setup.SetupError):
                bridge.configure_cloud_backup('icloud', str(self.destination))
            bridge.configure_cloud_backup('folder', str(self.destination))
        self.assertEqual(bridge.state['collector']['archive'], 'reader/private')
        self.assertTrue(bridge.cloud_backup_status()['enabled'])
        self.assertTrue(bridge.cloud_backup_status()['saved_at'])
        self.assertFalse(bridge.cloud_backup_status()['cloud_upload_verified'])
        self.assertEqual(launch.call_args.args[0], 'cloud_backup')
        installed = self.app / 'cloud_backup/archive_backup.py'
        self.assertTrue(installed.is_file())
        self.assertNotIn(self.token, (self.app / 'cloud_backup/config.json').read_text())


if __name__ == '__main__':
    unittest.main()
