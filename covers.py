"""Local, book-level cover library. Network access happens only on explicit import."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import ssl
import struct
import sys
from urllib.parse import unquote, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, HTTPSHandler, Request
import xml.etree.ElementTree as ET
import zipfile

import setup
from db import _normalized, clean_cover_url

MAX_IMAGE = 5 * 1024 * 1024
MAX_EPUB = 128 * 1024 * 1024
MAX_CATALOG = 4 * 1024 * 1024


def book_key(title, author):
    raw = json.dumps([_normalized(title), _normalized(author)], ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def image_kind(data):
    if not data or len(data) > MAX_IMAGE:
        raise ValueError('Choose a JPEG or PNG cover no larger than 5 MiB.')
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24:
        width, height = struct.unpack('>II', data[16:24])
        if not 0 < width <= 8000 or not 0 < height <= 8000 or width * height > 24_000_000:
            raise ValueError('Cover dimensions are too large.')
        return 'png'
    if data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'):
        # Bound JPEG dimensions before it reaches the native image decoder.
        offset = 2
        while offset + 4 <= len(data):
            if data[offset] != 0xff:
                break
            marker = data[offset + 1]
            if marker == 0xff:
                offset += 1
                continue
            if marker in (0xd8, 0x01) or 0xd0 <= marker <= 0xd7:
                offset += 2
                continue
            size = int.from_bytes(data[offset + 2:offset + 4], 'big')
            if size < 2 or offset + 2 + size > len(data):
                break
            if marker in (0xc0, 0xc1, 0xc2) and size >= 8:
                height, width = struct.unpack('>HH', data[offset + 5:offset + 9])
                if 0 < width <= 8000 and 0 < height <= 8000 and width * height <= 24_000_000:
                    return 'jpg'
                raise ValueError('Cover dimensions are too large.')
            offset += size + 2
    raise ValueError('Choose a valid JPEG or PNG cover.')


class CoverRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not clean_cover_url(newurl):
            raise ValueError('Cover redirect is not a supported image host.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url):
    url = clean_cover_url(url)
    if not url:
        raise ValueError('Cover URL is not a supported HTTPS image host.')
    context = ssl.create_default_context(cafile='/etc/ssl/cert.pem' if sys.platform == 'darwin' else None)
    opener = build_opener(CoverRedirect(), HTTPSHandler(context=context))
    with opener.open(Request(url, headers={'User-Agent': 'ReaderBridge/0.4', 'Accept': 'image/jpeg,image/png'}), timeout=8) as response:
        data = response.read(MAX_IMAGE + 1)
    image_kind(data)
    return data


def epub_cover(path):
    """Read only the declared EPUB cover; never extract archive members to disk."""
    if path.stat().st_size > MAX_EPUB:
        raise ValueError('Choose an EPUB no larger than 128 MiB.')
    with zipfile.ZipFile(path) as archive:
        def read(name, limit):
            info = archive.getinfo(name)
            if info.file_size > limit or info.flag_bits & 1:
                raise ValueError('EPUB cover is too large or encrypted.')
            with archive.open(info) as source:
                data = source.read(limit + 1)
            if len(data) > limit:
                raise ValueError('EPUB cover is too large.')
            return data
        def xml(name):
            data = read(name, 1024 * 1024)
            if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                raise ValueError('EPUB metadata contains unsupported XML declarations.')
            return ET.fromstring(data)
        container = xml('META-INF/container.xml')
        rootfile = next((e.attrib.get('full-path') for e in container.iter() if e.tag.endswith('}rootfile')), None)
        if not rootfile:
            raise ValueError('EPUB has no package document.')
        package = xml(rootfile)
        cover_id = next((e.attrib.get('content') for e in package.iter() if e.tag.endswith('}meta') and e.attrib.get('name') == 'cover'), None)
        items = [e for e in package.iter() if e.tag.endswith('}item')]
        cover = next((e for e in items if 'cover-image' in e.attrib.get('properties', '').split()), None)
        if cover is None and cover_id:
            cover = next((e for e in items if e.attrib.get('id') == cover_id), None)
        if cover is None:
            raise ValueError('This EPUB has no declared cover. Choose a JPEG or PNG instead.')
        href = unquote(cover.attrib.get('href', ''))
        if urlsplit(href).scheme or href.startswith('/') or '\\' in href:
            raise ValueError('EPUB cover must be inside the book.')
        member = posixpath.normpath(posixpath.join(posixpath.dirname(rootfile), href))
        if '..' in PurePosixPath(member).parts:
            raise ValueError('EPUB cover path is invalid.')
        data = read(member, MAX_IMAGE)
        image_kind(data)
        return data


class CoverLibrary:
    def __init__(self, app):
        self.root = setup.guarded(app / 'covers')
        self.catalog_path = setup.guarded(self.root / 'catalog.json')
        self.catalog = {}
        if self.catalog_path.exists():
            if self.catalog_path.stat().st_size > MAX_CATALOG:
                raise ValueError('Cover catalog exceeds its size limit.')
            self.catalog = json.loads(self.catalog_path.read_text())
            if not isinstance(self.catalog, dict):
                raise ValueError('Cover catalog is invalid.')

    def metadata(self, title, author):
        key = book_key(title, author)
        entry = self.catalog.get(key, {})
        if not isinstance(entry, dict):
            entry = {}
        filename = entry.get('image', '')
        path = ''
        if isinstance(filename, str) and len(filename) == 68 and filename[-4:] in ('.jpg', '.png') and all(c in '0123456789abcdef' for c in filename[:-4]):
            candidate = setup.guarded(self.root / filename)
            if candidate.is_file():
                path = str(candidate)
        return {'book_id': key, 'cover_url': clean_cover_url(entry.get('cover_url', '')), 'cover_path': path}

    def save(self):
        data = (json.dumps(self.catalog, ensure_ascii=False, indent=2) + '\n').encode()
        if len(data) > MAX_CATALOG:
            raise ValueError('Cover catalog exceeds its size limit.')
        setup.atomic_write(self.catalog_path, data)

    def put(self, title, author, data, url=''):
        extension = image_kind(data)
        filename = hashlib.sha256(data).hexdigest() + '.' + extension
        setup.atomic_write(setup.guarded(self.root / filename), data)
        self.catalog[book_key(title, author)] = {'image': filename, 'cover_url': clean_cover_url(url)}

    def import_rows(self, rows):
        # One request per distinct book, never one per quote. No requests on status.
        books = {}
        for row in rows:
            key = book_key(row['title'], row['author'])
            if row.get('cover_image') or row.get('cover_url'):
                books.setdefault(key, row)
        jobs = []
        saved = 0
        failures = 0
        for key, row in books.items():
            if self.metadata(row['title'], row['author'])['cover_path']:
                continue
            if row.get('cover_image'):
                try:
                    data = base64.b64decode(row['cover_image'], validate=True)
                    self.put(row['title'], row['author'], data, row.get('cover_url', ''))
                    saved += 1
                except (ValueError, TypeError):
                    failures += 1
            elif clean_cover_url(row.get('cover_url')):
                self.catalog[key] = {'cover_url': clean_cover_url(row['cover_url'])}
                jobs.append(row)
            else:
                failures += 1
        def fetch(row):
            try:
                return download(row['cover_url'])
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            for row, data in zip(jobs, pool.map(fetch, jobs)):
                if data is None:
                    failures += 1
                else:
                    self.put(row['title'], row['author'], data, row['cover_url'])
                    saved += 1
        if books:
            self.save()
        return saved, failures

    def export_rows(self, rows):
        output = []
        included = set()
        for row in rows:
            record = {k: v for k, v in row.items() if k != 'cover_path'}
            key = row['book_id']
            path = row.get('cover_path')
            if path and key not in included:
                data = setup.guarded(Path(path)).read_bytes()
                image_kind(data)
                record['cover_image'] = base64.b64encode(data).decode('ascii')
                included.add(key)
            output.append(record)
        return output
