"""Read English Kindle My Clippings exports without modifying source files."""
import hashlib
import re
from datetime import datetime

from db import preserve_creation_date


def clipping_date(metadata):
    """English Kindle/CrossPoint export dates have wall time, not a timezone."""
    match = re.search(r'\bAdded on\s+(.+)$', metadata)
    if not match:
        return ''
    raw = re.sub(r'^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+', '', match[1].strip())
    raw = raw.replace(',', '')
    parts = raw.split()
    if len(parts) not in (4, 5):
        return ''
    months = 'January February March April May June July August September October November December'.split()
    day, month, year, clock = parts[:4]
    if day in months:
        day, month = month, day
    try:
        time = [int(part) for part in clock.split(':')]
        if len(time) not in (2, 3):
            return ''
        hour, minute = time[:2]
        second = time[2] if len(time) == 3 else 0
        if len(parts) == 5:
            if parts[4] not in ('AM', 'PM') or not 1 <= hour <= 12:
                return ''
            hour = hour % 12 + (12 if parts[4] == 'PM' else 0)
        return datetime(int(year), months.index(month) + 1, int(day), hour, minute, second).isoformat()
    except (ValueError, OverflowError):
        return ''


def parse_clippings(text):
    rows = []
    seen = {}
    for entry in text.split('=========='):
        lines = entry.strip().splitlines()
        if len(lines) < 3 or not re.search(r'\b(?:Your )?Highlight\b', lines[1], re.I):
            continue
        body = '\n'.join(lines[2:]).strip()
        if not body:
            continue
        if len(body.encode('utf-8')) > 65536:
            raise ValueError('Highlight exceeds collector limit; source unchanged')
        heading = lines[0].strip()
        match = re.match(r'^(.*?)\s+\(([^()]*)\)$', heading)
        title, author = match.groups() if match else (heading, '')
        location = re.search(r'(?:Location|Loc\.)\s+([0-9-]+)', lines[1], re.I)
        location = location.group(1) if location else ''
        ident = hashlib.sha256('\0'.join((title, author, body, location)).encode()).hexdigest()
        row = {'id': ident, 'book_title': title, 'author': author, 'text': body, 'location': location}
        created = clipping_date(lines[1])
        if created:
            row['created_at'] = created
        if ident not in seen:
            rows.append(row)
            seen[ident] = row
        else:
            preserve_creation_date(seen[ident], row)
    return rows
