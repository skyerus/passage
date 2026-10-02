#!/usr/bin/env python3
"""Private, single-account KOSync-compatible service. No remote registration.

Clients use their existing Progress sync feature. Paired KOReader uploads use
revision checks; explicit user pushes may replace any position, including rereading.
"""
import argparse
from contextlib import closing
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid

MAX_BODY = 64 * 1024
DOCUMENT = re.compile(r'[a-fA-F0-9]{32}')


class Conflict(Exception):
    """A reader tried to replace a position it has not acknowledged."""
    def __init__(self, current):
        self.current = current


def validate(value, saved=False):
    if not isinstance(value, dict):
        raise ValueError('Invalid progress')
    result = {}
    for key, limit in [('document',32), ('progress',16384), ('device',256), ('device_id',256)]:
        text = value.get(key)
        if not isinstance(text, str) or not text or len(text.encode()) > limit or '\x00' in text:
            raise ValueError('Invalid progress field')
        result[key] = text
    if not DOCUMENT.fullmatch(result['document']):
        raise ValueError('Invalid document identity')
    percentage = value.get('percentage')
    if isinstance(percentage, bool) or not isinstance(percentage, (int,float,str)):
        raise ValueError('Invalid percentage')
    percentage = float(percentage)
    if not math.isfinite(percentage) or not 0 <= percentage <= 1:
        raise ValueError('Invalid percentage')
    result['percentage'] = percentage
    # Optional metadata is display-only. Never use a filename as a storage path.
    if isinstance(value.get('metadata'), dict):
        metadata = {k:v for k,v in value['metadata'].items() if k in ('title','authors','filename') and isinstance(v,str) and len(v.encode()) <= 4096 and '\x00' not in v}
        if metadata:
            result['metadata'] = metadata
    if saved:
        timestamp = value.get('timestamp')
        if type(timestamp) not in (int,float) or not math.isfinite(timestamp) or not 0 <= timestamp <= 253402300799:
            raise ValueError('Invalid receipt timestamp')
        result['timestamp'] = int(timestamp)
        if 'reader_bridge_revision' in value:
            revision = value['reader_bridge_revision']
            if not isinstance(revision,str) or not DOCUMENT.fullmatch(revision):
                raise ValueError('Invalid progress revision')
            result['reader_bridge_revision'] = revision
    return result


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with closing(self.connect()) as con:
            con.executescript('''PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS positions(document TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS uploads(device_id TEXT PRIMARY KEY, device TEXT NOT NULL, received_at INTEGER NOT NULL, count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS guarded_devices(device_id TEXT PRIMARY KEY);
            ''')
            # Upgrade in place without changing saved positions or receipt times.
            with con:
                con.execute('BEGIN IMMEDIATE')
                for document, payload in con.execute('SELECT document,payload FROM positions').fetchall():
                    item = json.loads(payload)
                    if not item.get('reader_bridge_revision'):
                        item['reader_bridge_revision'] = uuid.uuid4().hex
                        con.execute('UPDATE positions SET payload=? WHERE document=?',(json.dumps(item,ensure_ascii=False),document))
        os.chmod(self.path, 0o600)

    def connect(self):
        con = sqlite3.connect(self.path, timeout=5)
        con.execute('PRAGMA synchronous=FULL')
        return con

    def put(self, value):
        item = validate(value)
        item['timestamp'] = int(time.time())
        control = value.get('metadata',{}).get('reader_bridge') if isinstance(value.get('metadata'),dict) else None
        if control is not None:
            if (not isinstance(control,dict) or type(control.get('version')) is not int or control['version'] != 1
                    or not isinstance(control.get('base_revision'),str)
                    or control['base_revision'] not in ('unknown','missing') and not DOCUMENT.fullmatch(control['base_revision'])
                    or type(control.get('force',False)) is not bool):
                raise ValueError('Invalid progress guard')
        with closing(self.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            old = con.execute('SELECT payload FROM positions WHERE document=?', (item['document'],)).fetchone()
            old = json.loads(old[0]) if old else None
            guarded = control is not None or con.execute('SELECT 1 FROM guarded_devices WHERE device_id=?',(item['device_id'],)).fetchone()
            if guarded:
                if old and old['progress'] == item['progress'] and old['percentage'] == item['percentage']:
                    # An echo must not steal ownership or make an old position look new.
                    return {'document':item['document'],'timestamp':old['timestamp'],
                            'reader_bridge_revision':old['reader_bridge_revision']}
                if control is None or (not control.get('force') and old and control['base_revision'] != old['reader_bridge_revision']):
                    raise Conflict(old)
            if 'metadata' not in item and old:
                metadata = old.get('metadata')
                if metadata: item['metadata'] = metadata
            item['reader_bridge_revision'] = uuid.uuid4().hex
            con.execute('INSERT INTO positions VALUES(?,?) ON CONFLICT(document) DO UPDATE SET payload=excluded.payload', (item['document'], json.dumps(item, ensure_ascii=False)))
            con.execute('INSERT INTO uploads VALUES(?,?,?,1) ON CONFLICT(device_id) DO UPDATE SET device=excluded.device,received_at=excluded.received_at,count=count+1', (item['device_id'], item['device'], item['timestamp']))
        return {'document':item['document'], 'timestamp':item['timestamp'], 'reader_bridge_revision':item['reader_bridge_revision']}

    def require_guard(self, device_id):
        if not isinstance(device_id,str) or not device_id or len(device_id.encode()) > 256 or '\x00' in device_id:
            raise ValueError('Invalid guarded device')
        with closing(self.connect()) as con, con:
            con.execute('INSERT OR IGNORE INTO guarded_devices VALUES(?)',(device_id,))

    def seed(self, rows, newer=False):
        items = [validate(item, saved=True) for item in rows]
        with closing(self.connect()) as con, con:
            con.execute('BEGIN IMMEDIATE')
            before = con.total_changes
            for item in items:
                old = con.execute('SELECT payload FROM positions WHERE document=?',(item['document'],)).fetchone()
                if old and (not newer or json.loads(old[0])['timestamp'] >= item['timestamp']): continue
                # Restores and migrations invalidate tokens held by earlier clients.
                item['reader_bridge_revision'] = uuid.uuid4().hex
                con.execute('INSERT INTO positions VALUES(?,?) ON CONFLICT(document) DO UPDATE SET payload=excluded.payload',(item['document'],json.dumps(item,ensure_ascii=False)))
            return con.total_changes - before

    def get(self, document):
        with closing(self.connect()) as con:
            row = con.execute('SELECT payload FROM positions WHERE document=?', (document,)).fetchone()
        return json.loads(row[0]) if row else None


def read_archive(path):
    path = Path(path)
    if not path.is_file(): return []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('PRAGMA query_only=ON')
        return [validate(json.loads(r[0]), saved=True) for r in con.execute('SELECT payload FROM positions ORDER BY document')]


def read_uploads(path):
    path = Path(path)
    if not path.is_file(): return []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as con:
        con.execute('PRAGMA query_only=ON')
        return [{'device':d,'received_at':t,'count':n} for d,t,n in con.execute('SELECT device,received_at,count FROM uploads ORDER BY received_at DESC LIMIT 20')]


def credentials(directory):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / 'credentials.json'
    if path.exists():
        value = json.loads(path.read_text())
        if not isinstance(value.get('username'),str) or not value['username'] or not isinstance(value.get('password'),str) or len(value['password']) < 20:
            raise ValueError('Invalid local progress credentials; preserve and recover them')
        return value
    value = {'username':'readerbridge-' + secrets.token_hex(4), 'password':secrets.token_urlsafe(24)}
    with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as out:
        json.dump(value, out); out.flush(); os.fsync(out.fileno())
    return value


def auth_headers(account):
    return {'x-auth-user':account['username'], 'x-auth-key':hashlib.md5(account['password'].encode()).hexdigest(), 'Accept':'application/vnd.koreader.v1+json'}


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, *args):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(*args)
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try: super().process_request(request, address)
        except BaseException:
            self.slots.release(); raise
    def process_request_thread(self, request, address):
        try: super().process_request_thread(request, address)
        finally: self.slots.release()
    def handle_error(self, request, address):
        # No request bodies, device IDs, account headers or paths in logs.
        pass


def server(store, account, host, port):
    expected = auth_headers(account)
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'
        def setup(self):
            super().setup(); self.connection.settimeout(10)
        def log_message(self, *args): pass
        def reply(self, status, value):
            body = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers(); self.wfile.write(body)
        def authenticated(self):
            return all(len(self.headers.get_all(k,[])) == 1 and hmac.compare_digest(self.headers[k].encode(),expected[k].encode()) for k in ('x-auth-user','x-auth-key'))
        def do_GET(self):
            if self.path == '/healthcheck':
                return self.reply(200, {'state':'OK', 'service':'reader-bridge-progress', 'revision_guard':1})
            if not self.authenticated(): return self.reply(401, {'message':'Unauthorized','code':2001})
            if self.path == '/users/auth': return self.reply(200, {'username':account['username']})
            document = self.path.removeprefix('/syncs/progress/')
            if not self.path.startswith('/syncs/progress/') or not DOCUMENT.fullmatch(document):
                return self.reply(404, {'message':'Not found'})
            try: value = store.get(document)
            except (sqlite3.Error,OSError): return self.reply(503, {'message':'Storage unavailable; retry'})
            self.reply(200 if value else 404, value or {'message':'No progress saved','reader_bridge_revision':'missing'})
        def do_POST(self):
            # The app provisions one private account locally; readers use Login.
            self.reply(403, {'message':'Pair this reader in Reader Bridge; account registration is disabled'})
        def do_PUT(self):
            if not self.authenticated(): return self.reply(401, {'message':'Unauthorized','code':2001})
            if self.path != '/syncs/progress': return self.reply(404, {'message':'Not found'})
            try:
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length',[])) != 1:
                    raise ValueError('Length required')
                size = int(self.headers['Content-Length'])
                if not 0 < size <= MAX_BODY: return self.reply(413, {'message':'Request too large'})
                if self.headers.get_content_type() != 'application/json': return self.reply(415, {'message':'JSON required'})
                raw = self.rfile.read(size)
                if len(raw) != size: raise ValueError('Incomplete request')
                value = store.put(json.loads(raw))
            except Conflict as exc:
                return self.reply(409, {'message':'A newer position is available. Pull it, or explicitly push this device to replace it.',
                                        'reader_bridge_conflict':True, 'current':exc.current})
            except (ValueError,UnicodeError,OverflowError): return self.reply(400, {'message':'Invalid progress'})
            except (sqlite3.Error,OSError): return self.reply(503, {'message':'Storage unavailable; retry'})
            self.reply(200, value)
    return BoundedServer((host,port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    server(Store(args.state_dir/'positions.sqlite3'), credentials(args.state_dir), '0.0.0.0', args.port).serve_forever()


if __name__ == '__main__': main()
