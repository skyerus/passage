# Desktop dependencies

Passage's application and original helper code use the repository's MIT license.

The app bundles unmodified CPython 3.13.15 from Astral's Python Build Standalone release `20260929`. Both macOS architecture downloads and their SHA-256 digests are pinned in `runtime.json`. The runtime includes its Python and pip license files. Additional upstream component license texts are retained in `licenses/python-standalone`, copied from upstream commit `b498734a5791d0e6786695a226fd398a41c6f7f6` (the release tag). These supplemental files cover the upstream distribution's available components; their presence does not imply every optional component is included in this macOS runtime.

- [Python Build Standalone source](https://github.com/astral-sh/python-build-standalone/tree/b498734a5791d0e6786695a226fd398a41c6f7f6)
- [Runtime release and source downloads](https://github.com/astral-sh/python-build-standalone/releases/tag/20260929)
- [Upstream Python licensing notes](https://github.com/astral-sh/python-build-standalone/blob/b498734a5791d0e6786695a226fd398a41c6f7f6/python-licenses.rst)

The app does not bundle KOReader itself, jailbreak tools, CrossPoint firmware binaries, books, fonts, dictionaries, or Calibre-Web. It includes Passage's KOReader plugin. Optional firmware and library setup download and build/install their separately licensed dependencies on the user's Mac, just as the command-line installer does. See `docs/UPSTREAM-SOURCES.md` for those boundaries.
