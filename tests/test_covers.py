import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import collector
import covers
from db import clean_cover_url, merge
import setup
import test_desktop

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aL1sAAAAASUVORK5CYII=')
URL = 'https://m.media-amazon.com/images/I/example.jpg'


class CoverTests(unittest.TestCase):
    def test_url_policy_and_redirects(self):
        self.assertEqual(clean_cover_url(URL), URL)
        for url in ('file:///etc/passwd', 'http://m.media-amazon.com/a.jpg', 'https://127.0.0.1/a.jpg',
                    'https://m.media-amazon.com.evil.test/a.jpg', 'https://user:password@m.media-amazon.com/a',
                    'https://m.media-amazon.com:8084/a', 'https://m.media-amazon.com/a\nb', None):
            self.assertEqual(clean_cover_url(url), '')
        with self.assertRaises(ValueError):
            covers.CoverRedirect().redirect_request(None, None, 302, '', {}, 'http://localhost:8084')

    def test_metadata_is_book_level_read_only_and_offline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / 'not-created'
            library = covers.CoverLibrary(root)
            self.assertFalse(root.exists())
            self.assertEqual(library.metadata('A Book', 'Writer')['cover_path'], '')
            with patch.object(covers, 'download', return_value=PNG) as fetch:
                saved, failed = library.import_rows([
                    {'title': 'A Book', 'author': 'Writer', 'cover_url': URL},
                    {'title': '  a book ', 'author': 'WRITER', 'cover_url': URL}])
            self.assertEqual((saved, failed), (1, 0))
            fetch.assert_called_once_with(URL)
            with patch.object(covers, 'download', side_effect=AssertionError('network')):
                reopened = covers.CoverLibrary(root)
                self.assertTrue(Path(reopened.metadata('a book', 'writer')['cover_path']).is_file())
                self.assertEqual(reopened.import_rows([{'title': 'A Book', 'author': 'Writer', 'cover_url': URL}]), (0, 0))
            self.assertEqual(Path(reopened.metadata('A Book', 'Writer')['cover_path']).stat().st_mode & 0o777, 0o600)
            self.assertEqual(reopened.metadata('A Book', 'Different writer')['cover_path'], '')

    def test_epub2_and_epub3_extract_declared_cover_only(self):
        with tempfile.TemporaryDirectory() as temp:
            for epub3 in (True, False):
                path = Path(temp) / 'book.epub'
                with zipfile.ZipFile(path, 'w') as out:
                    out.writestr('META-INF/container.xml', '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="EPUB/content.opf"/></rootfiles></container>')
                    meta = '' if epub3 else '<metadata><meta name="cover" content="jacket"/></metadata>'
                    properties = ' properties="cover-image"' if epub3 else ''
                    out.writestr('EPUB/content.opf', '<package xmlns="http://www.idpf.org/2007/opf">' + meta + '<manifest><item id="jacket" href="images/cover.png" media-type="image/png"' + properties + '/></manifest></package>')
                    out.writestr('EPUB/images/cover.png', PNG)
                    out.writestr('../../escape.txt', 'must not extract')
                self.assertEqual(covers.epub_cover(path), PNG)
                self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_invalid_and_oversized_images_are_rejected(self):
        for data in (b'not-an-image', b'<svg/>', b'\xff\xd8\xff\xd9', PNG + b'x' * covers.MAX_IMAGE):
            with self.assertRaises(ValueError):
                covers.image_kind(data)

    def test_collector_and_github_preserve_covers_on_replay_and_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            store = collector.Store(Path(temp) / 'inbox.sqlite3')
            item = {'id': 'one', 'book_title': 'Book', 'author': 'Writer', 'text': 'Quote', 'cover_url': URL}
            payload = {'source': 'koreader', 'device_id': 'fixture', 'highlights': [item]}
            store.accept(payload)
            item.pop('cover_url')
            store.accept(payload)
            self.assertEqual(collector.archive_rows(store.pending())[0]['cover_url'], URL)
            merged = merge([], [{'book_title': 'Book', 'author': 'Writer', 'highlight': 'First'},
                                {'book_title': 'Book', 'author': 'Writer', 'highlight': 'Second', 'cover_url': URL}])
            self.assertTrue(all(row['cover_url'] == URL for row in merged))
            store.accept({**payload, 'highlights': [{'id': 'one', 'deleted': True}]})
            store.accept(payload)
            self.assertEqual(collector.archive_rows(store.pending()), [])


class ArchiveCoverTests(unittest.TestCase):
    # Reuse the real HTTP fixture without rediscovering the original test cases.
    setUp = test_desktop.DesktopTests.setUp
    tearDown = test_desktop.DesktopTests.tearDown
    initialize = test_desktop.DesktopTests.initialize
    server = test_desktop.DesktopTests.server
    item = test_desktop.DesktopTests.item
    def test_json_import_cover_export_reimport_and_delete(self):
        with self.server():
            archive = self.root / 'archive.json'
            record = {'book_title': 'Book', 'author': 'Author', 'highlight': 'Quote', 'created_at': '2020-01-02', 'cover_url': URL}
            archive.write_text(json.dumps([record, {**record, 'highlight': 'Second'}]))
            with patch.object(covers, 'download', return_value=PNG) as fetch:
                first = self.bridge.mutate('import_archive', {'path': str(archive)})
                repeated = self.bridge.mutate('import_archive', {'path': str(archive)})
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(first['highlight_count'], 2)
            self.assertEqual(repeated['highlight_count'], 2)
            self.assertEqual(first['import_result'], {'highlights': 2, 'covers': 1, 'unavailable': 0})
            with patch.object(covers, 'download', side_effect=AssertionError('status network')):
                status = self.bridge.status()
            self.assertEqual(len(status['books']), 1)
            self.assertEqual(status['books'][0]['count'], 2)
            self.assertTrue(all(row['cover_path'] for row in status['highlights']))
            output = self.root / 'export.json'
            self.bridge.mutate('export', {'path': str(output)})
            exported = json.loads(output.read_text())['highlights']
            self.assertTrue(all('cover_path' not in row for row in exported))
            self.assertEqual(sum('cover_image' in row for row in exported), 1)
            self.assertTrue(all(row['created_at'] == '2020-01-02' for row in exported))
            other = covers.CoverLibrary(self.root / 'other-app')
            with patch.object(covers, 'download', side_effect=AssertionError('portable cover network')):
                self.assertEqual(other.import_rows(exported), (1, 0))
            ident = status['highlights'][0]['id']
            self.store.accept({'source': 'koreader', 'device_id': 'reader-bridge-archive-import', 'highlights': [{'id': ident, 'deleted': True}]})
            self.bridge.mutate('import_archive', {'path': str(archive)})
            self.assertEqual(self.bridge.status()['highlight_count'], 1)

    def test_cover_failure_does_not_lose_quotes_and_can_retry(self):
        with self.server():
            archive = self.root / 'archive.json'
            archive.write_text(json.dumps([{'title': 'Book', 'author': 'Author', 'text': 'Quote', 'cover_url': URL}]))
            with patch.object(covers, 'download', side_effect=OSError('offline')):
                result = self.bridge.mutate('import_archive', {'path': str(archive)})
            self.assertEqual(result['import_result']['unavailable'], 1)
            self.assertEqual(result['highlight_count'], 1)
            with patch.object(covers, 'download', return_value=PNG):
                result = self.bridge.mutate('cache_covers', {})
            self.assertEqual(result['import_result']['covers'], 1)
            self.assertTrue(result['highlights'][0]['cover_path'])

    def test_all_archive_validated_before_first_write(self):
        with self.server():
            archive = self.root / 'archive.json'
            archive.write_text(json.dumps([{'title': 'Book', 'author': '', 'text': 'Valid'}, {'title': 'Bad', 'text': 123}]))
            with self.assertRaises(setup.SetupError):
                self.bridge.mutate('import_archive', {'path': str(archive)})
            self.assertEqual(self.bridge.status()['highlight_count'], 0)

    def test_book_filter_applies_before_500_quote_limit(self):
        self.initialize()
        for number in range(502):
            self.store.accept({'source': 'koreader', 'device_id': 'fixture', 'highlights': [{**self.item(str(number), str(number)), 'book_title': 'Book' if number < 501 else 'Z last'}]})
        status = self.bridge.status()
        self.assertEqual(len(status['books']), 2)
        target = next(book for book in status['books'] if book['title'] == 'Z last')
        filtered = self.bridge.status(book_id=target['id'])
        self.assertEqual(len(filtered['highlights']), 1)
        self.assertEqual(filtered['highlights'][0]['title'], 'Z last')

    def test_manual_cover_propagates_to_new_highlights_and_export(self):
        self.initialize()
        self.store.accept({'source': 'koreader', 'device_id': 'fixture', 'highlights': [self.item()]})
        cover = self.root / 'cover.png'
        cover.write_bytes(PNG)
        self.bridge.mutate('set_cover', {'title': 'Book', 'author': 'Author', 'path': str(cover)})
        self.store.accept({'source': 'crosspoint', 'device_id': 'x4', 'highlights': [self.item('two', 'Another quote')]})
        status = self.bridge.status()
        self.assertEqual(len({row['cover_path'] for row in status['highlights']}), 1)
        self.assertTrue(status['highlights'][0]['cover_path'])
        with self.assertRaises(setup.SetupError):
            self.bridge.mutate('set_cover', {'title': 'Wrong book', 'author': 'Author', 'path': str(cover)})

    def test_archive_deletions_survive_transfer_and_stale_replay(self):
        with self.server():
            self.store.accept({'source': 'koreader', 'device_id': 'old', 'highlights': [self.item()]})
            self.store.accept({'source': 'koreader', 'device_id': 'old', 'highlights': [{'id': '1', 'deleted': True}]})
            path = self.root / 'deleted-archive.json'
            self.bridge.mutate('export', {'path': str(path)})
            archive = json.loads(path.read_text())
            self.assertEqual(archive['highlights'], [])
            self.assertEqual(len(archive['tombstones']), 1)
        other = test_desktop.DesktopTests()
        other.setUp()
        try:
            with other.server():
                result = other.bridge.mutate('import_archive', {'path': str(path)})
                self.assertEqual(result['highlight_count'], 0)
                other.store.accept({'source': 'crosspoint', 'device_id': 'new', 'highlights': [other.item()]})
                self.assertEqual(other.bridge.status()['highlight_count'], 0)
        finally:
            other.tearDown()

    def test_deletion_import_requires_auth_and_rejects_bad_hashes(self):
        from urllib.error import HTTPError
        with self.server() as (port, token):
            endpoint = f'http://127.0.0.1:{port}/v1/tombstones'
            with self.assertRaises(HTTPError) as error:
                setup.http(endpoint, json.dumps({'tombstones': ['a' * 64]}).encode(), headers={'Content-Type': 'application/json'})
            self.assertEqual(error.exception.code, 401)
            with self.assertRaises(HTTPError) as error:
                setup.http(endpoint, json.dumps({'tombstones': ['invalid']}).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
            self.assertEqual(error.exception.code, 400)
            self.assertEqual(self.store.tombstones(), set())

    def test_corrupt_cover_cache_cannot_block_recovery_export(self):
        self.initialize()
        self.store.accept({'source': 'koreader', 'device_id': 'fixture', 'highlights': [self.item()]})
        tombstone = 'a' * 64
        self.store.import_tombstones([tombstone])
        catalog = self.app / 'covers/catalog.json'
        catalog.parent.mkdir()
        for index, content in enumerate(('not json', '[]', '{}' + ' ' * covers.MAX_CATALOG)):
            catalog.write_text(content)
            output = self.root / f'recovered-{index}.json'
            result = self.bridge.mutate('export', {'path': str(output)})
            archive = json.loads(output.read_text())
            self.assertEqual(archive['highlights'][0]['text'], 'A private quote')
            self.assertEqual(archive['tombstones'], [tombstone])
            self.assertNotIn('cover_path', archive['highlights'][0])
            self.assertIn('omitted', result['export_warning'])
