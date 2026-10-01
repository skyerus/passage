import copy
from datetime import datetime, timezone
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

DB_PATH = Path(__file__).parent / "highlights.json"
TOMBSTONES_PATH = Path(__file__).parent / "highlight-tombstones.json"


def load() -> list[dict]:
    if not DB_PATH.exists():
        return []
    return json.loads(DB_PATH.read_text())


def save(quotes: list[dict]) -> None:
    DB_PATH.write_text(json.dumps(quotes, indent=2, ensure_ascii=False) + "\n")


def _normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _key(quote):
    # Include book and author: identical short passages in different books remain distinct.
    return tuple(_normalized(quote.get(k, "")) for k in ("book_title", "author", "highlight"))


def quote_key(quote):
    """Stable deletion identity shared by collector and Amazon importer."""
    canonical = json.dumps(_key(quote), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_tombstones(values):
    if not isinstance(values, list) or any(not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value) for value in values):
        raise ValueError("invalid highlight tombstones")
    return set(values)


def load_tombstones(path=None):
    path = Path(path) if path is not None else TOMBSTONES_PATH
    return validate_tombstones(json.loads(path.read_text())) if path.exists() else set()


def recorded_date(raw):
    """Parse a recorded date; never substitute import or upload time."""
    if not isinstance(raw, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?', raw):
        return None
    try:
        value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def preserve_creation_date(target, incoming):
    """Enrich missing dates and keep the earliest recorded creation of a quote."""
    old, new = recorded_date(target.get('created_at')), recorded_date(incoming.get('created_at'))
    if new is not None and (old is None or new < old):
        target['created_at'] = incoming['created_at']


def clean_cover_url(value):
    """Only known public book-image hosts; never credentials, local URLs or ports."""
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 33 for c in value):
        return ''
    try:
        url = urlsplit(value)
        hosts = {'m.media-amazon.com', 'images-na.ssl-images-amazon.com',
                 'images-eu.ssl-images-amazon.com', 'images.amazon.com', 'covers.openlibrary.org'}
        if url.scheme == 'https' and url.hostname in hosts and not url.username and not url.password and url.port in (None, 443) and not url.fragment:
            return value
    except ValueError:
        pass
    return ''


def merge(existing: list[dict], scraped: list[dict], tombstones=()) -> list[dict]:
    """Union without truncating text or dropping legacy entries; preserve legacy metadata."""
    deleted = set(tombstones)
    merged = copy.deepcopy([q for q in existing if quote_key(q) not in deleted])
    by_key = {_key(q): q for q in merged}
    covers = {(_normalized(q.get("book_title", "")), _normalized(q.get("author", ""))): q["cover_url"] for q in merged if q.get("cover_url")}
    for incoming in scraped:
        if quote_key(incoming) in deleted:
            continue
        q = copy.deepcopy(incoming)
        key = _key(q)
        if not q.get("cover_url"):
            q["cover_url"] = covers.get(key[:2], "")
        if key not in by_key:
            merged.append(q)
            by_key[key] = q
        else:
            target = by_key[key]
            preserve_creation_date(target, q)
            if not target.get("cover_url") and q.get("cover_url"):
                target["cover_url"] = q["cover_url"]
    covers = {(_normalized(q.get("book_title", "")), _normalized(q.get("author", ""))): q["cover_url"] for q in merged if q.get("cover_url")}
    for q in merged:
        if not q.get("cover_url"):
            q["cover_url"] = covers.get(_key(q)[:2], "")
    return merged
