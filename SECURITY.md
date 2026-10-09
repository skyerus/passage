# Reporting security issues

Do not include pairing files, collector tokens, queue files, SQLite databases, account exports, private repository addresses, library credentials, books or full device backups in an issue. Redact screenshots and logs before sharing them. `python3 setup.py doctor` avoids quote text, device IDs and local mount paths.

Report vulnerabilities through [GitHub's private security reporting form](https://github.com/skyerus/passage/security/advisories/new). GitHub sign-in is required. Include the affected Passage version, a minimal reproduction using synthetic data, and the potential impact. Do not post vulnerability details in a public issue. Never post a working credential. Rotate any exposed token and re-pair the readers.

Passage is for a trusted home LAN. Highlight and local reading-position HTTP traffic is not encrypted, and CrossPoint File Transfer exposes device files while it is open. Do not forward the collector, progress, or library ports through a router. Close File Transfer after setup.

The personal archive is separate from the public source repository. Backups and Git history can retain deleted content. Current archive deletion suppresses stale reimports; it does not promise forensic erasure or automatic deletion from every reader. For ordinary setup or sync problems, use the [support guide](SUPPORT.md).
