import hashlib
import http.client
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import zipfile
from unittest.mock import patch

import book_sync


def epub(path, title='Test Book'):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip')
        z.writestr('META-INF/container.xml', '<container><rootfiles><rootfile full-path="content.opf"/></rootfiles></container>')
        z.writestr('content.opf', '<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>' + title + '</dc:title></metadata></package>')
    return path


def export():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('content.kfx', 'synthetic fixture, not a real book')
    return stream.getvalue()


class BookSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = dict(token='private-token-' * 4, converter='converter', calibredb='calibredb',
                           calibre_config=str(self.root / 'calibre-config'), library=str(self.root / 'library'))
        self.inbox = book_sync.Inbox(self.root / 'state', self.config)
        self.server = book_sync.make_server(self.inbox, '127.0.0.1', 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.shutdown)

    def shutdown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, body=None, authenticated=True, digest=None):
        headers = {'Authorization': 'Bearer ' + self.config['token']} if authenticated else {}
        if body is not None:
            headers['X-Content-SHA256'] = digest or hashlib.sha256(body).hexdigest()
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        result = response.status, response.read()
        conn.close()
        return result

    def upload(self, asin='B000000001'):
        return self.request('POST', '/v1/import/' + asin, export())

    def test_authentication_checksums_and_bad_archives_never_queue(self):
        for method, path in [('GET', '/v1/books'), ('POST', '/v1/import/B000000001')]:
            self.assertEqual(self.request(method, path, export() if method == 'POST' else None,
                                          authenticated=False)[0], 401)
        self.assertEqual(self.request('POST', '/v1/import/B000000001', export(), digest='0' * 64)[0], 400)
        self.assertEqual(self.request('POST', '/v1/import/B000000001', b'not a zip')[0], 400)
        self.assertEqual(self.request('POST', '/v1/import/../../escape', export())[0], 404)
        self.assertEqual(self.inbox.status('B000000001')['state'], 'missing')
        self.assertEqual(list((self.inbox.root / 'incoming').iterdir()), [])

    def test_duplicate_upload_and_restart_preserve_one_job_and_original_source(self):
        self.assertEqual(self.upload()[0], 202)
        original = (self.inbox.root / 'incoming/B000000001.kfx-zip').read_bytes()
        self.assertEqual(self.upload()[0], 202)
        with self.inbox.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM books').fetchone()[0], 1)
            db.execute("UPDATE books SET state='processing'")
        restarted = book_sync.Inbox(self.inbox.root, self.config)
        self.assertEqual(restarted.status('B000000001')['state'], 'queued')
        self.assertEqual((self.inbox.root / 'incoming/B000000001.kfx-zip').read_bytes(), original)

    def test_seeded_books_download_byte_identically_and_cannot_be_replaced(self):
        source = epub(self.root / 'existing.epub')
        self.inbox.seed('B000000002', source)
        status, body = self.request('GET', '/v1/download/B000000002')
        self.assertEqual(status, 200)
        self.assertEqual(body, source.read_bytes())
        before = self.inbox.status('B000000002')
        self.assertEqual(self.upload('B000000002')[0], 202)
        self.assertEqual(self.inbox.status('B000000002'), before)
        with self.assertRaises(ValueError):
            self.inbox.seed('B000000002', epub(self.root / 'replacement.epub', 'Changed'))
        path = self.inbox.root / 'books' / before['filename']
        path.write_bytes(b'corruption')
        self.assertEqual(self.request('GET', '/v1/download/B000000002')[0], 503)

    def test_failed_conversion_is_durable_and_not_published(self):
        self.upload()
        with patch.object(self.inbox, 'library_book', return_value=None), \
                patch.object(self.inbox, 'run_command', side_effect=RuntimeError('not supported')):
            self.assertTrue(self.inbox.process_one())
        row = self.inbox.status('B000000001')
        self.assertEqual(row['state'], 'failed')
        self.assertGreater(row['retry_at'], 0)
        self.assertFalse(self.inbox.process_one(), 'Failed conversion must back off')
        self.assertEqual(self.request('GET', '/v1/download/B000000001')[0], 404)
        self.assertEqual(json.loads(self.request('GET', '/v1/books')[1]), {'books': []})

    def test_conversion_then_import_recovery_never_reconverts_or_changes_epub(self):
        self.upload()
        commands = []
        def command(args, log, timeout):
            commands.append(args[0])
            if args[0] == 'converter':
                epub(Path(args[-1]))
            else:
                raise RuntimeError('library busy')
        with patch.object(self.inbox, 'library_book', return_value=None), patch.object(self.inbox, 'run_command', command):
            self.inbox.process_one()
        self.assertEqual(commands, ['converter', 'calibredb'])
        canonical = next((self.inbox.root / 'books').glob('*.epub'))
        digest = book_sync.sha256(canonical)
        with self.inbox.db() as db:
            db.execute('UPDATE books SET retry_at=0')
        # Simulate add completing just before a crash: discover its ASIN on retry.
        with patch.object(self.inbox, 'library_book', return_value=canonical), \
                patch.object(self.inbox, 'run_command', side_effect=AssertionError('must not rerun')):
            self.inbox.process_one()
        self.assertEqual(self.inbox.status('B000000001')['state'], 'ready')
        self.assertEqual(self.inbox.status('B000000001')['sha256'], digest)

    def test_unicode_names_fit_device_limit(self):
        source = epub(self.root / 'unicode.epub', '界' * 80)
        self.inbox.seed('B000000003', source)
        self.assertLessEqual(len(self.inbox.status('B000000003')['filename'].encode()), 240)

    def test_receipts_require_the_ready_book_checksum(self):
        self.inbox.seed('B000000004', epub(self.root / 'receipt.epub'))
        path='/v1/received/B000000004'
        self.assertEqual(self.request('POST', path, json.dumps({'sha256': 'wrong'}).encode())[0], 400)
        with self.inbox.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM deliveries').fetchone()[0], 0)
        body=json.dumps({'sha256': self.inbox.status('B000000004')['sha256']}).encode()
        self.assertEqual(self.request('POST', path, body)[0], 200)
        self.assertEqual(self.request('POST', path, body)[0], 200)
        with self.inbox.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM deliveries').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
