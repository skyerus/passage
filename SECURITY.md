# Reporting security issues

Do not include pairing files, collector tokens, queue files, SQLite databases, account exports, private repository addresses, library credentials, books or full device backups in an issue. Redact screenshots and logs before sharing them. `python3 setup.py doctor` avoids quote text, device IDs and local mount paths.

Report sensitive vulnerabilities privately through the repository's GitHub security reporting channel when available; otherwise contact a maintainer before posting details publicly. Never post a working credential. Rotate any exposed token and re-pair the readers.

Reader Bridge is for a trusted home LAN. Highlight HTTP traffic is not encrypted, and Xteink File Transfer exposes device files while it is open. Do not forward the collector or library ports through a router. Close File Transfer after setup.

The personal archive is separate from the public source repository. Backups and Git history can retain deleted content. Current archive deletion suppresses stale reimports; it does not promise forensic erasure or automatic deletion from every reader.
