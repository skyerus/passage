"""Read English Kindle My Clippings exports without modifying source files."""
import hashlib
import re


def parse_clippings(text):
    rows = []
    seen = set()
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
        if ident not in seen:
            rows.append({'id': ident, 'book_title': title, 'author': author, 'text': body, 'location': location})
            seen.add(ident)
    return rows
