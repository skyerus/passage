"""Bounded device artwork and shared book identity; no network dependencies."""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import zlib
from urllib.parse import unquote_to_bytes

from db import _normalized

MAX_IMAGE = 5 * 1024 * 1024

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
        offset, found_data, ended = 8, False, False
        compressed = []
        while offset + 12 <= len(data):
            size = int.from_bytes(data[offset:offset+4], 'big')
            end = offset + 12 + size
            if end > len(data):
                raise ValueError('Truncated PNG cover')
            kind = data[offset+4:offset+8]
            payload = data[offset+8:offset+8+size]
            checksum = int.from_bytes(data[offset+8+size:end], 'big')
            if zlib.crc32(kind + payload) & 0xffffffff != checksum:
                raise ValueError('Invalid PNG checksum')
            if offset == 8 and (kind != b'IHDR' or size != 13):
                raise ValueError('Invalid PNG header')
            if kind == b'IDAT':
                compressed.append(payload)
            found_data = found_data or kind == b'IDAT'
            offset = end
            if kind == b'IEND':
                ended = size == 0 and offset == len(data)
                break
        if not ended or not found_data:
            raise ValueError('Incomplete PNG cover')
        depth, color, compression, filtering, interlace = data[24:29]
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
        depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
        if not channels or depth not in depths[color] or compression or filtering or interlace not in (0, 1):
            raise ValueError('Unsupported PNG header')
        passes = [(0, 0, 1, 1)] if not interlace else [(0,0,8,8),(4,0,8,8),(0,4,4,8),(2,0,4,4),(0,2,2,4),(1,0,2,2),(0,1,1,2)]
        expected = 0
        for x, y, dx, dy in passes:
            w, h = max(0, (width-x+dx-1)//dx), max(0, (height-y+dy-1)//dy)
            if w and h:
                expected += (1 + (w*channels*depth+7)//8) * h
        inflater, inflated = zlib.decompressobj(), 0
        try:
            for chunk in compressed:
                while chunk:
                    inflated += len(inflater.decompress(chunk, 65536))
                    if inflated > expected:
                        raise ValueError('PNG data exceeds declared dimensions')
                    chunk = inflater.unconsumed_tail
            if not inflater.eof or inflater.unused_data or inflated != expected:
                raise ValueError('Invalid PNG image data')
        except zlib.error as exc:
            raise ValueError('Invalid PNG compression') from exc
        return 'png'
    if data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9'):
        offset, frame, scan, entropy = 2, False, False, False
        while offset < len(data):
            if data[offset] != 0xff:
                break
            while offset < len(data) and data[offset] == 0xff:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker == 0xd9:
                if frame and scan and entropy and offset == len(data):
                    return 'jpg'
                break
            if marker in (0, 0xd8) or 0xd0 <= marker <= 0xd7:
                break
            if marker == 0x01:
                continue
            if offset + 2 > len(data):
                break
            size = int.from_bytes(data[offset:offset+2], 'big')
            if size < 2 or offset + size > len(data):
                break
            if marker in (0xc0, 0xc1, 0xc2):
                if size < 11:
                    break
                precision = data[offset+2]
                height, width = struct.unpack('>HH', data[offset+3:offset+7])
                components = data[offset+7]
                if (precision not in (8, 12) or components not in (1, 3, 4) or size != 8 + 3 * components
                        or not 0 < width <= 8000 or not 0 < height <= 8000 or width * height > 24_000_000):
                    raise ValueError('Invalid JPEG frame or dimensions')
                frame = True
            if marker == 0xda:
                if not frame or size < 8 or data[offset+2] not in (1, 2, 3, 4) or size != 6 + 2 * data[offset+2]:
                    break
                scan = True
            offset += size
            if marker == 0xda:
                start = offset
                # Skip entropy-coded bytes, stuffed FFs and restart markers.
                while offset < len(data):
                    if data[offset] != 0xff:
                        offset += 1
                        continue
                    if offset + 1 < len(data) and (data[offset+1] == 0 or 0xd0 <= data[offset+1] <= 0xd7):
                        offset += 2
                        continue
                    break
                entropy = entropy or offset > start
    raise ValueError('Choose a valid JPEG or PNG cover.')



def decode_metadata(value, required=False):
    if not isinstance(value, str) or len(value) > 12288 or re.search(r'%(?![0-9a-fA-F]{2})', value):
        raise ValueError('Invalid cover metadata')
    text = unquote_to_bytes(value).decode('utf-8')
    if len(text.encode('utf-8')) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in text) or (required and not text.strip()):
        raise ValueError('Invalid cover metadata')
    return text


def store_image(directory, data):
    """Immutable content address. Acknowledgement follows file and DB fsync."""
    extension = image_kind(data)
    digest = hashlib.sha256(data).hexdigest()
    root = Path(directory) / 'covers'
    if root.is_symlink():
        raise ValueError('Invalid cover directory')
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = root / (digest + '.' + extension)
    if target.is_symlink():
        raise ValueError('Invalid cover file')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix='.upload-', delete=False) as out:
            temporary = Path(out.name)
            os.chmod(out.name, 0o600)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        temporary.replace(target)
        fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return digest, extension


def stored_path(directory, digest, extension):
    if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest) or extension not in ('jpg', 'png'):
        return ''
    root = Path(directory) / 'covers'
    path = root / (digest + '.' + extension)
    if root.is_symlink() or path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_IMAGE:
        return ''
    return str(path)
