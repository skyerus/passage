"""Exercise the device wire protocol against a new, empty bridge over real HTTP."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote
import unittest

import collector
import covers
import device_covers
import test_desktop

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=')


class DeviceCoverTests(unittest.TestCase):
    setUp = test_desktop.DesktopTests.setUp
    tearDown = test_desktop.DesktopTests.tearDown
    initialize = test_desktop.DesktopTests.initialize
    server = test_desktop.DesktopTests.server
    item = test_desktop.DesktopTests.item
    upload = test_desktop.DesktopTests.upload

    def send_cover(self, port, token, title='Book', author='Author', data=PNG, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        fields = {'Authorization': 'Bearer ' + token, 'Content-Type': 'image/png',
                  'X-Book-Title': quote(title, safe=''), 'X-Book-Author': quote(author, safe='')}
        fields.update(headers or {})
        try:
            connection.request('POST', '/v1/covers', data, fields)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_first_highlight_and_device_cover_appear_without_import(self):
        for source in ('koreader', 'crosspoint'):
            with self.subTest(source=source), self.server() as (port, token):
                title, author = 'Unseen café / 読書 ' + source, 'Zoë & 作者'
                item = {**self.item(source), 'book_title': title, 'author': author}
                self.upload(port, token, source, source, [item])
                row = next(r for r in self.bridge.status()['highlights'] if r['title'] == title)
                self.assertEqual(row['cover_path'], '')
                code, result = self.send_cover(port, token, title, author)
                self.assertEqual((code, result), (200, {'status': 'stored', 'sha256': hashlib.sha256(PNG).hexdigest()}))
                with patch.object(covers, 'download', side_effect=AssertionError('No internet')):
                    row = next(r for r in self.bridge.status()['highlights'] if r['title'] == title)
                self.assertEqual(Path(row['cover_path']).read_bytes(), PNG)
                self.assertEqual(row['created_at'], item['created_at'])
                self.assertEqual(row['source'], source)

    def test_retry_restart_and_second_highlight_reuse_cover(self):
        with self.server() as (port, token):
            self.assertEqual(self.send_cover(port, token)[0], 200)
            self.assertEqual(self.send_cover(port, token)[0], 200)  # response lost, safe replay
            self.upload(port, token, 'koreader', 'device', [self.item('1'), self.item('2', 'Another')])
            collector.Store(self.store.path)  # reopen as on collector restart
            status = self.bridge.status()
            self.assertEqual(status['highlight_count'], 2)
            paths = {r['cover_path'] for r in status['highlights']}
            self.assertEqual(len(paths), 1)
            self.assertEqual(len(list((Path(self.store.path).parent / 'covers').iterdir())), 1)
            self.assertEqual(Path(paths.pop()).stat().st_mode & 0o777, 0o600)

    def test_invalid_covers_never_block_quote_and_can_be_retried(self):
        with self.server() as (port, token):
            self.upload(port, token, 'crosspoint', 'reader', [self.item()])
            for bad in (b'<svg/>', PNG[:24], PNG[:-1], PNG[:45] + b'garbage',
                        bytes.fromhex('ffd8ffc000080800010001ffd9')):
                self.assertEqual(self.send_cover(port, token, data=bad)[0], 400)
                self.assertEqual(self.bridge.status()['highlight_count'], 1)
                self.assertEqual(self.bridge.status()['books'][0]['cover_path'], '')
            self.assertEqual(self.send_cover(port, token)[0], 200)
            self.assertTrue(self.bridge.status()['books'][0]['cover_path'])

    def test_storage_failure_is_not_acknowledged_and_quote_is_retained(self):
        with self.server() as (port, token):
            self.upload(port, token, 'koreader', 'device', [self.item()])
            with patch.object(collector, 'store_image', side_effect=OSError('disk full')):
                self.assertEqual(self.send_cover(port, token)[0], 503)
            self.assertEqual(self.bridge.status()['highlight_count'], 1)
            self.assertEqual(self.bridge.status()['books'][0]['cover_path'], '')
            self.assertEqual(self.send_cover(port, token)[0], 200)

    def test_auth_limits_and_metadata_validation(self):
        with self.server() as (port, token):
            self.assertEqual(self.send_cover(port, 'wrong')[0], 401)
            for headers in ({'Content-Type': 'text/plain'}, {'Content-Type': 'image/jpeg'},
                            {'X-Book-Title': '%zz'}, {'X-Book-Title': '%FF'},
                            {'X-Book-Title': '%0aInjected'}, {'X-Book-Title': ''},
                            {'X-Book-Title': 'x' * 4097}):
                self.assertIn(self.send_cover(port, token, headers=headers)[0], (400, 415))
            self.assertEqual(self.send_cover(port, token, headers={'Content-Length': str(device_covers.MAX_IMAGE + 1)})[0], 413)
            self.assertEqual(self.send_cover(port, token, author='')[0], 200)
            self.assertEqual(self.bridge.status()['highlight_count'], 0)

    def test_concurrent_books_do_not_lose_cover_metadata(self):
        with self.server() as (port, token):
            with ThreadPoolExecutor(max_workers=4) as workers:
                codes = list(workers.map(lambda i: self.send_cover(port, token, title='Book ' + str(i))[0], range(8)))
            self.assertEqual(codes, [200] * 8)
            with self.store.connect() as con:
                self.assertEqual(con.execute('SELECT count(*) FROM book_covers').fetchone()[0], 8)

    def test_late_device_artwork_cannot_replace_accepted_cover(self):
        import struct, zlib
        def chunk(kind, payload):
            return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
        another = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0')) + chunk(b'IEND', b'')
        with self.server() as (port, token):
            first = self.send_cover(port, token)[1]
            late = self.send_cover(port, token, data=another)[1]
            self.assertEqual(late, first)
            self.assertEqual(len(list((Path(self.store.path).parent / 'covers').iterdir())), 1)

    def test_auto_cover_survives_export_and_manual_override_wins(self):
        with self.server() as (port, token):
            self.upload(port, token, 'koreader', 'device', [self.item()])
            self.send_cover(port, token)
            output = self.root / 'portable.json'
            self.bridge.mutate('export', {'path': str(output)})
            record = json.loads(output.read_text())['highlights'][0]
            self.assertEqual(base64.b64decode(record['cover_image']), PNG)
            self.assertNotIn('cover_path', record)
            library = covers.CoverLibrary(self.app)
            library.put('Book', 'Author', PNG); library.save()
            self.send_cover(port, token)
            self.assertEqual(self.bridge.status()['books'][0]['cover_path'], library.metadata('Book', 'Author')['cover_path'])

    def test_jpeg_requires_frame_scan_and_complete_structure(self):
        with self.assertRaises(ValueError):
            device_covers.image_kind(bytes.fromhex('ffd8ffc000080800010001ffd9'))

    def test_old_schema_and_missing_image_remain_usable(self):
        self.initialize()
        self.store.accept({'source': 'koreader', 'device_id': 'device', 'highlights': [self.item()]})
        self.store.accept_cover('Book', 'Author', PNG, 'image/png')
        row = self.bridge.status()['highlights'][0]
        Path(row['cover_path']).unlink()
        self.assertEqual(self.bridge.status()['highlights'][0]['cover_path'], '')
        with self.store.connect() as con:
            con.execute('DROP TABLE book_covers')
        self.assertEqual(self.bridge.status()['highlight_count'], 1)
        self.assertEqual(self.bridge.status()['books'][0]['cover_path'], '')
