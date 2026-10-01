"""Portable Reader Bridge or kindle-highlights JSON, with stable quote identities."""
import json
from collector import validate
from db import clean_cover_url, quote_key, validate_tombstones


def parse_archive(data):
    try:
        values = json.loads(data)
    except (ValueError, UnicodeError):
        raise ValueError('Choose a Reader Bridge or Kindle highlights JSON archive.')
    tombstones = set()
    if isinstance(values, dict):
        if values.get('format') != 'reader-bridge' or values.get('version') != 1:
            raise ValueError('This archive format is not supported.')
        tombstones = validate_tombstones(values.get('tombstones', []))
        values = values.get('highlights')
    if not isinstance(values, list) or (not values and not tombstones) or len(values) > 10000 or len(tombstones) > 10000:
        raise ValueError('Archive must contain between 1 and 10,000 highlights.')
    rows = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError('Every archive entry must be a highlight.')
        row = {'book_title': value.get('book_title', value.get('title', '')),
               'author': value.get('author', ''), 'text': value.get('highlight', value.get('text', ''))}
        if not all(isinstance(v, str) for v in row.values()):
            raise ValueError('Book title, author and highlight must be text.')
        row['id'] = quote_key({'book_title': row['book_title'], 'author': row['author'], 'highlight': row['text']})
        if value.get('deleted'):
            if not row['text'].strip() or not row['book_title'].strip():
                raise ValueError('A deleted archive entry needs its book and quote identity.')
            tombstones.add(row['id'])
            continue
        if 'created_at' in value:
            row['created_at'] = value['created_at']
        if clean_cover_url(value.get('cover_url')):
            row['cover_url'] = clean_cover_url(value['cover_url'])
        source = value.get('source') if value.get('source') in ('koreader', 'crosspoint') else 'koreader'
        _, _, clean = validate({'source': source, 'device_id': 'reader-bridge-archive-import', 'highlights': [row]})
        image = value.get('cover_image', '')
        if not isinstance(image, str) or len(image) > 7 * 1024 * 1024:
            raise ValueError('Embedded cover must be base64 text no larger than 7 MiB.')
        rows.append({'source': source, 'item': clean[0], 'cover': {
            'title': row['book_title'], 'author': row['author'], 'cover_url': value.get('cover_url', ''), 'cover_image': image}})
    if not rows and not tombstones:
        raise ValueError('Archive has no live highlights to import.')
    return rows, sorted(tombstones)
