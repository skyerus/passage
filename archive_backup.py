"""Versioned, portable archive snapshots. Cloud clients upload completed files.

The live database and credentials always stay local. This worker is independent
of the collector, so an unavailable backup destination never blocks a reader.
"""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import uuid
import zipfile

MAX_ARCHIVE = 256 * 1024 * 1024
MAX_JSON = 64 * 1024 * 1024
MAX_IMAGE = 5 * 1024 * 1024
HEX = re.compile(r'[a-f0-9]{64}')
IMAGE = re.compile(r'[a-f0-9]{64}\.(?:jpg|png)')


def guarded(path):
    path = Path(path).expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Choose a folder without symbolic links.')
    return path


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def atomic(path, data):
    path = guarded(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
            temporary = Path(out.name)
            os.chmod(temporary, 0o600)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


@contextmanager
def lock(directory):
    directory = guarded(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with guarded(directory / '.backup.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def image_file(path):
    path = guarded(path)
    if not IMAGE.fullmatch(path.name) or not path.is_file() or path.stat().st_size > MAX_IMAGE:
        raise ValueError('A cover is unavailable. Download it locally and retry.')
    data = path.read_bytes()
    valid_header = data.startswith(b'\x89PNG\r\n\x1a\n') if path.suffix == '.png' else data.startswith(b'\xff\xd8\xff')
    if not valid_header or hashlib.sha256(data).hexdigest() != path.stem:
        raise ValueError('A cover failed its integrity check.')
    return data


def capture(database, app):
    """One read transaction; only allowlisted archive data, never app settings."""
    database, app = guarded(database), guarded(app)
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        records = [{'source':s, 'device_id':d, 'highlights':[json.loads(p)]}
                   for s,d,p in con.execute('SELECT source,device,payload FROM inbox ORDER BY source,device,id')]
        deleted = [r[0] for r in con.execute('SELECT quote_key FROM tombstones ORDER BY quote_key')]
        history = list(con.execute('SELECT source,device,id,quote_key FROM quote_history ORDER BY source,device,id,quote_key'))
        covers = {}
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='book_covers'").fetchone():
            covers = {k: str(guarded(database.parent / 'covers' / (digest + '.' + ext)))
                      for k,digest,ext in con.execute('SELECT book_key,sha256,extension FROM book_covers')
                      if HEX.fullmatch(k) and HEX.fullmatch(digest) and ext in ('jpg', 'png')}
    catalog_path = guarded(app / 'covers/catalog.json')
    catalog = {}
    if catalog_path.is_file():
        if catalog_path.stat().st_size > MAX_JSON:
            raise ValueError('Cover catalog exceeds the backup limit.')
        catalog = json.loads(catalog_path.read_text())
        for key, entry in catalog.items():
            name = entry.get('image', '')
            if HEX.fullmatch(key) and IMAGE.fullmatch(name):
                covers[key] = str(guarded(app / 'covers' / name))
    images = {}
    for path in covers.values():
        images[Path(path).name] = image_file(path)
    manifest = {'format':'reader-bridge-backup', 'version':1, 'records':records,
                'tombstones':deleted, 'history':history,
                'covers':{k:Path(v).name for k,v in sorted(covers.items())}}
    content = encode(manifest)
    if len(content) > MAX_JSON or len(content) + sum(map(len, images.values())) > MAX_ARCHIVE:
        raise ValueError('Archive exceeds the 256 MiB backup limit.')
    return content, images


def snapshot(database, app, destination, state_dir):
    """Retain immutable snapshots; skip unchanged content, never prune user data."""
    state_dir = guarded(state_dir)
    with lock(state_dir):
        root = guarded(destination)
        if not root.is_dir():
            raise ValueError('Backup folder is unavailable. Reconnect it and retry.')
        content, images = capture(database, app)
        digest = hashlib.sha256(content + b''.join(name.encode() for name in sorted(images))).hexdigest()
        receipt_path = guarded(state_dir / 'receipt.json')
        previous = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {}
        if previous.get('digest') == digest and previous.get('destination') == str(root) and guarded(previous['path']).is_file():
            previous.pop('error', None)
            previous['checked_at'] = datetime.now(timezone.utc).isoformat()
            atomic(receipt_path, encode(previous))
            return previous
        now = datetime.now(timezone.utc)
        name = now.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:12] + '.readerbridge'
        target = root / name
        with tempfile.TemporaryDirectory(dir=state_dir) as staging:
            path = Path(staging) / name
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('archive.json', content)
                for image, data in images.items():
                    archive.writestr('covers/' + image, data)
            blob = path.read_bytes()
            atomic(target, blob)
            if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(blob).digest():
                raise ValueError('Backup readback failed. Previous backups are retained.')
        result = {'digest':digest, 'destination':str(root), 'path':str(target),
                  'saved_at':now.isoformat(), 'checked_at':now.isoformat(), 'cloud_upload_verified':False}
        atomic(receipt_path, encode(result))
        return result


def read_snapshot(path):
    """Validate the entire bundle before a restore can mutate anything."""
    from collector import validate
    from db import validate_tombstones
    from device_covers import image_kind
    path = guarded(path)
    if not path.is_file() or path.stat().st_size > MAX_ARCHIVE:
        raise ValueError('Choose a downloaded Reader Bridge backup under 256 MiB.')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        if len(names) != len(set(names)) or len(names) > 20000 or sum(e.file_size for e in entries) > MAX_ARCHIVE:
            raise ValueError('Invalid or oversized backup.')
        if any(n != 'archive.json' and not (n.startswith('covers/') and IMAGE.fullmatch(n[7:])) for n in names):
            raise ValueError('Unexpected backup contents.')
        if 'archive.json' not in names or archive.getinfo('archive.json').file_size > MAX_JSON:
            raise ValueError('Missing or oversized archive manifest.')
        manifest = json.loads(archive.read('archive.json'))
        if manifest.get('format') != 'reader-bridge-backup' or manifest.get('version') != 1:
            raise ValueError('Unsupported backup version.')
        if not isinstance(manifest.get('records'), list) or len(manifest['records']) > 100000:
            raise ValueError('Invalid backup records.')
        identities = set()
        for batch in manifest['records']:
            source, device, items = validate(batch)
            if len(items) != 1:
                raise ValueError('Invalid backup record batch.')
            key = (source, device, items[0]['id'])
            if key in identities:
                raise ValueError('Duplicate backup identity.')
            identities.add(key)
            allowed = {'id', 'deleted', 'book_title', 'author', 'text', 'note', 'created_at', 'location', 'cover_url'}
            original = batch['highlights'][0]
            if not set(original) <= allowed or ('cover_url' in original and (not isinstance(original['cover_url'], str) or len(original['cover_url']) > 4096)):
                raise ValueError('Unsupported record fields.')
        if not isinstance(manifest.get('history'), list) or not isinstance(manifest.get('covers'), dict):
            raise ValueError('Invalid backup metadata.')
        validate_tombstones(manifest['tombstones'])
        for row in manifest['history']:
            if not isinstance(row, list) or len(row) != 4 or tuple(row[:3]) not in identities or not HEX.fullmatch(row[3]):
                raise ValueError('Invalid deletion history.')
        images = {}
        for key, name in manifest['covers'].items():
            if not HEX.fullmatch(key) or not IMAGE.fullmatch(name) or 'covers/' + name not in names:
                raise ValueError('Invalid cover manifest.')
            if archive.getinfo('covers/' + name).file_size > MAX_IMAGE:
                raise ValueError('Cover exceeds 5 MiB.')
            data = archive.read('covers/' + name)
            if hashlib.sha256(data).hexdigest() != name[:-4]:
                raise ValueError('Cover checksum does not match.')
            header = b'\x89PNG\r\n\x1a\n' if name.endswith('.png') else b'\xff\xd8\xff'
            if not data.startswith(header):
                raise ValueError('Invalid cover format.')
            if image_kind(data) != name[-3:]:
                raise ValueError('Cover image does not match its format.')
            images[name] = data
    return manifest, images


def restore(path, database, app):
    """Merge a verified snapshot; current edits/deletions always win.

    Publish acknowledgements and credentials never move between installations.
    A pre-restore snapshot gives the operation its own recovery point.
    """
    from collector import Store, item_key
    from db import preserve_creation_date
    manifest, images = read_snapshot(path)
    database, app = guarded(database), guarded(app)
    recovery = app / 'backups/before-restore'
    recovery.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshot(database, app, recovery, app / 'restore-snapshot')
    store = Store(database)
    for name, data in images.items():
        target = guarded(database.parent / 'covers' / name)
        if target.exists() and target.read_bytes() != data:
            raise ValueError('Existing cover failed its checksum. Restore stopped.')
        atomic(target, data)
    with store.connect() as con:
        con.execute('BEGIN IMMEDIATE')
        con.executemany('INSERT OR IGNORE INTO tombstones(quote_key,published) VALUES(?,0)', [(k,) for k in manifest['tombstones']])
        con.executemany('INSERT OR IGNORE INTO quote_history VALUES(?,?,?,?)', manifest['history'])
        for batch in manifest['records']:
            item = batch['highlights'][0]
            key = (batch['source'], batch['device_id'], item['id'])
            current = con.execute('SELECT payload FROM inbox WHERE source=? AND device=? AND id=?', key).fetchone()
            if current:
                old = json.loads(current[0])
                if not old.get('deleted') and not item.get('deleted') and item_key(old) == item_key(item):
                    preserve_creation_date(old, item)
                item = old
            data = json.dumps(item, ensure_ascii=False, sort_keys=True)
            revision = hashlib.sha256(data.encode()).hexdigest()
            con.execute('INSERT INTO inbox(source,device,id,payload,revision) VALUES(?,?,?,?,?) ON CONFLICT(source,device,id) DO UPDATE SET payload=excluded.payload,revision=excluded.revision', key + (data, revision))
            if not item.get('deleted'):
                con.execute('INSERT OR IGNORE INTO quote_history VALUES(?,?,?,?)', key + (item_key(item),))
        con.execute('CREATE TABLE IF NOT EXISTS book_covers (book_key TEXT PRIMARY KEY, sha256 TEXT NOT NULL, extension TEXT NOT NULL)')
        con.executemany('INSERT OR IGNORE INTO book_covers VALUES(?,?,?)', [(key,name[:-4],name[-3:]) for key,name in manifest['covers'].items()])
        store._scrub_deleted(con)
    return len(manifest['records'])


def run_once(config, state_dir):
    try:
        result = snapshot(config['database'], config['app'], config['destination'], state_dir)
    except Exception:
        path = guarded(Path(state_dir) / 'receipt.json')
        result = json.loads(path.read_text()) if path.is_file() else {}
        result['error'] = 'Backup needs attention. Check the folder is available and has free space, then retry.'
        atomic(path, encode(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    while True:
        config = json.loads(guarded(args.state_dir / 'config.json').read_text())
        run_once(config, args.state_dir)
        if args.once:
            break
        time.sleep(60)


if __name__ == '__main__':
    main()
