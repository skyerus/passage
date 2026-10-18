"""Private LAN inbox for already decrypted Kindle exports; see docs/BOOK-SYNC.md.

Never replaces a published EPUB: binary identity is shared reading progress.
The device performs decryption using its separately installed export tool.
"""
import argparse
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import xml.etree.ElementTree as ET
import zipfile

MAX_BOOK = 256 * 1024 * 1024
ASIN = re.compile(r"[A-Z0-9]{10}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def sha256(path):
    hasher = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_zip(path, epub=False):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if (not entries or len(entries) > 20000 or
                sum(item.file_size for item in entries) > MAX_BOOK * 4):
            raise ValueError('Archive exceeds limits')
        for item in entries:
            if (item.filename.startswith(('/', '\\')) or
                    '..' in item.filename.replace('\\', '/').split('/') or
                    item.flag_bits & 1):
                raise ValueError('Unsafe or encrypted ZIP')
        if epub:
            if archive.getinfo('mimetype').file_size > 64 or archive.getinfo('META-INF/container.xml').file_size > 65536:
                raise ValueError('EPUB container exceeds limits')
            if archive.read('mimetype') != b'application/epub+zip':
                raise ValueError('Invalid EPUB mimetype')
            root = ET.fromstring(archive.read('META-INF/container.xml'))
            package = root.find('.//{*}rootfile')
            if package is None:
                raise ValueError('Missing EPUB package')
            name = package.attrib['full-path']
            if archive.getinfo(name).file_size > 4 * 1024 * 1024:
                raise ValueError('EPUB metadata exceeds limits')
            metadata = ET.fromstring(archive.read(name))
            title = metadata.find('.//{http://purl.org/dc/elements/1.1/}title')
            return title.text if title is not None and title.text else 'Book'


class Inbox:
    def __init__(self, root, config):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config = config
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.import_lock = threading.Lock()
        for directory in ('incoming', 'books', 'logs'):
            (self.root / directory).mkdir(exist_ok=True, mode=0o700)
        self.database = self.root / 'books.sqlite3'
        with self.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS books (
                asin TEXT PRIMARY KEY, state TEXT NOT NULL, source_sha TEXT,
                title TEXT, filename TEXT, sha256 TEXT, size INTEGER,
                attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0,
                error TEXT)''')
            db.execute("UPDATE books SET state='queued' WHERE state='processing'")
            db.execute('CREATE TABLE IF NOT EXISTS deliveries (asin TEXT PRIMARY KEY, sha256 TEXT NOT NULL, received_at REAL NOT NULL)')

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def status(self, asin):
        with self.db() as db:
            row = db.execute('SELECT * FROM books WHERE asin=?', (asin,)).fetchone()
        return dict(row) if row else {'asin': asin, 'state': 'missing'}

    def ready(self):
        with self.db() as db:
            return [dict(row) for row in db.execute(
                "SELECT asin,title,filename,sha256,size FROM books WHERE state='ready' ORDER BY asin")]

    def receive(self, asin, stream, size, digest):
        # Serialize admission; never overwrite an accepted source on retry.
        with self.import_lock:
            target = self.root / 'incoming' / (asin + '.kfx-zip')
            fd, temporary = tempfile.mkstemp(dir=target.parent, suffix='.part')
            try:
                hasher = hashlib.sha256()
                with os.fdopen(fd, 'wb') as output:
                    remaining = size
                    while remaining:
                        chunk = stream.read(min(65536, remaining))
                        if not chunk:
                            raise ValueError('Incomplete upload')
                        hasher.update(chunk)
                        output.write(chunk)
                        remaining -= len(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if not hmac.compare_digest(hasher.hexdigest(), digest):
                    raise ValueError('Upload checksum mismatch')
                validate_zip(temporary)
                if self.status(asin)['state'] != 'missing':
                    return
                os.replace(temporary, target)
                with self.db() as db:
                    db.execute("INSERT INTO books(asin,state,source_sha) VALUES(?,'queued',?)", (asin, digest))
                self.wake.set()
            finally:
                Path(temporary).unlink(missing_ok=True)

    def publish(self, asin, source):
        title = validate_zip(source, epub=True)
        name = re.sub(r'[^\w .()-]', '_', title, flags=re.UNICODE).strip(' .')[:80] or 'Book'
        name = name.encode('utf-8')[:180].decode('utf-8', errors='ignore')
        filename = f'{name} - {asin}.epub'
        destination = self.root / 'books' / filename
        # On recovery, reuse the exact previously generated file.
        if destination != source:
            if destination.exists():
                if sha256(destination) != sha256(source):
                    raise ValueError('Refusing to replace an existing EPUB')
            else:
                temporary = destination.with_suffix('.part')
                shutil.copyfile(source, temporary)
                with temporary.open('rb') as stream:
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
        return {'title': title, 'filename': filename, 'sha256': sha256(destination),
                'size': destination.stat().st_size}

    def mark_ready(self, asin, details):
        with self.db() as db:
            db.execute("""UPDATE books SET state='ready',title=:title,filename=:filename,
                sha256=:sha256,size=:size,error=NULL WHERE asin=:asin""", dict(details, asin=asin))

    def seed(self, asin, source):
        if not ASIN.fullmatch(asin):
            raise ValueError('Invalid ASIN')
        if self.status(asin)['state'] != 'missing':
            raise ValueError('Book is already registered')
        details = self.publish(asin, Path(source))
        with self.db() as db:
            db.execute("INSERT INTO books(asin,state) VALUES(?,'queued')", (asin,))
        self.mark_ready(asin, details)

    def library_book(self, asin):
        library = Path(self.config['library']).resolve()
        database = library / 'metadata.db'
        with contextlib.closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute('''SELECT b.path,d.name FROM books b JOIN identifiers i ON i.book=b.id
                JOIN data d ON d.book=b.id WHERE i.type='asin' AND i.val=? AND d.format='EPUB' ''',
                (asin,)).fetchone()
        if not row:
            return None
        path = (library / row[0] / (row[1] + '.epub')).resolve()
        if not path.is_relative_to(library) or not path.is_file():
            raise ValueError('Invalid library path')
        return path

    def run_command(self, arguments, log, timeout):
        environment = dict(os.environ, CALIBRE_CONFIG_DIRECTORY=self.config['calibre_config'])
        subprocess.run(arguments, check=True, env=environment, stdout=log,
                       stderr=subprocess.STDOUT, timeout=timeout)

    def process_one(self):
        with self.db() as db:
            row = db.execute("SELECT * FROM books WHERE state IN ('queued','failed') AND retry_at<=? "
                             'ORDER BY rowid LIMIT 1', (time.time(),)).fetchone()
            if not row:
                return False
            asin = row['asin']
            db.execute("UPDATE books SET state='processing',attempts=attempts+1 WHERE asin=?", (asin,))
        try:
            existing = self.library_book(asin)
            if existing:
                details = self.publish(asin, existing)
            else:
                output = self.root / 'incoming' / (asin + '.epub')
                with (self.root / 'logs' / (asin + '.log')).open('ab') as log:
                    if not output.exists():
                        temporary = self.root / 'incoming' / (asin + '.converting.epub')
                        temporary.unlink(missing_ok=True)
                        self.run_command([self.config['converter'],
                            str(self.root / 'incoming' / (asin + '.kfx-zip')), str(temporary)], log, 900)
                        validate_zip(temporary, epub=True)
                        os.replace(temporary, output)
                    details = self.publish(asin, output)
                    self.run_command([self.config['calibredb'], 'add', '--with-library',
                        self.config['library'], '--duplicates', '--identifier', 'asin:' + asin,
                        str(self.root / 'books' / details['filename'])], log, 120)
                added = self.library_book(asin)
                if not added or sha256(added) != details['sha256']:
                    raise ValueError('Library copy was not verified')
            self.mark_ready(asin, details)
        except Exception as error:
            # Details stay in a private local log, never include command/config in API errors.
            with self.db() as db:
                db.execute("UPDATE books SET state='failed',retry_at=?,error=? WHERE asin=?",
                           (time.time() + min(3600, 60 * 2 ** min(row['attempts'], 6)),
                            type(error).__name__, asin))
        return True

    def worker(self):
        while not self.stopping.is_set():
            self.wake.clear()
            if not self.process_one():
                self.wake.wait(15)


def make_server(inbox, host, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def response(self, status, value):
            body = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def authenticated(self):
            supplied = self.headers.get('Authorization', '')
            if not hmac.compare_digest(supplied.encode(), ('Bearer ' + inbox.config['token']).encode()):
                self.response(401, {'error': 'Authentication required'})
                return False
            return True

        def do_GET(self):
            if not self.authenticated():
                return
            if self.path == '/v1/books':
                self.response(200, {'books': inbox.ready()})
                return
            match = re.fullmatch(r'/v1/(status|download)/([A-Z0-9]{10})', self.path)
            if not match:
                self.response(404, {'error': 'Not found'})
                return
            operation, asin = match.groups()
            row = inbox.status(asin)
            if operation == 'status':
                self.response(200, {key: row.get(key) for key in ('asin', 'state', 'error')})
                return
            if row['state'] != 'ready':
                self.response(404, {'error': 'Book is not ready'})
                return
            path = inbox.root / 'books' / row['filename']
            if not path.is_file() or path.stat().st_size != row['size'] or sha256(path) != row['sha256']:
                self.response(503, {'error': 'Stored EPUB requires repair'})
                return
            with path.open('rb') as stream:
                self.send_response(200)
                self.send_header('Content-Type', 'application/epub+zip')
                self.send_header('Content-Length', str(row['size']))
                self.send_header('X-Content-SHA256', row['sha256'])
                self.end_headers()
                shutil.copyfileobj(stream, self.wfile, 65536)

        def do_POST(self):
            if not self.authenticated():
                return
            receipt = re.fullmatch(r'/v1/received/([A-Z0-9]{10})', self.path)
            if receipt or self.path == '/v1/device-status':
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 4096 or self.headers.get('Transfer-Encoding'):
                        raise ValueError('Invalid status body')
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict):
                        raise ValueError('Invalid status')
                    if receipt:
                        row = inbox.status(receipt[1])
                        if row['state'] != 'ready' or body.get('sha256') != row['sha256']:
                            raise ValueError('Receipt checksum mismatch')
                        with inbox.db() as db:
                            db.execute('INSERT OR REPLACE INTO deliveries VALUES(?,?,?)',
                                       (receipt[1], row['sha256'], time.time()))
                    else:
                        status = {key: str(body.get(key, ''))[:1000] for key in ('message', 'detail')}
                        status.update(ok=body.get('ok') is True, received_at=time.time())
                        temporary = inbox.root / 'device-status.tmp'
                        temporary.write_text(json.dumps(status) + '\n')
                        os.replace(temporary, inbox.root / 'device-status.json')
                    self.response(200, {'status': 'stored'})
                except (ValueError, OSError):
                    self.response(400, {'error': 'Invalid device receipt'})
                return
            match = re.fullmatch(r'/v1/import/([A-Z0-9]{10})', self.path)
            if not match:
                self.response(404, {'error': 'Not found'})
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                digest = self.headers.get('X-Content-SHA256', '')
                if self.headers.get('Transfer-Encoding') or not 0 < size <= MAX_BOOK or not DIGEST.fullmatch(digest):
                    raise ValueError('Invalid upload headers')
                asin = match[1]
                inbox.receive(asin, self.rfile, size, digest)
                self.response(202, {'state': inbox.status(asin)['state']})
            except (ValueError, KeyError, zipfile.BadZipFile, OSError):
                self.response(400, {'error': 'Upload was not accepted'})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8086)
    parser.add_argument('--seed', nargs=2, metavar=('ASIN', 'EXISTING_EPUB'))
    args = parser.parse_args()
    config = json.loads((args.state_dir / 'config.json').read_text())
    if len(config.get('token', '')) < 32:
        parser.error('A private token of at least 32 characters is required')
    # One process owns conversion and the journal, including restart recovery.
    import fcntl
    args.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (args.state_dir / 'service.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inbox = Inbox(args.state_dir, config)
        if args.seed:
            inbox.seed(*args.seed)
            return
        server = make_server(inbox, args.host, args.port)
        threading.Thread(target=inbox.worker, daemon=True).start()
        try:
            server.serve_forever()
        finally:
            inbox.stopping.set()
            inbox.wake.set()
            server.server_close()


if __name__ == '__main__':
    main()
