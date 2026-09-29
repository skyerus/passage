# Reader Bridge

Set up a Mac, a Kindle running KOReader, and an Xteink X4 Pro running CrossPoint with one guided command:

```sh
git clone https://github.com/skyerus/reader-bridge.git
cd reader-bridge
python3 setup.py
```

You need macOS, Python 3.10+, Git, and [GitHub CLI](https://cli.github.com/) signed in with `gh auth login`. The wizard asks before creating your own **private** highlight archive. It never chooses the developer's archive.

- **Highlights:** an authenticated Mac collector stores uploads durably, then publishes them to your archive. Offline uploads retry. Deletions stay deleted across retries and later imports.
- **Kindle:** installs the Shared highlights plugin into an existing KOReader installation, preserving its identity and pending queue. Jailbreak and KOReader installation remain guided, model-specific prerequisites.
- **X4 Pro:** builds pinned custom CrossPoint source locally, verifies the uploaded firmware and pairing files, then pauses for the on-device update. Other Xteink models are not supported by this firmware profile.
- **Reading progress:** walks you through using the same CrossPoint Sync account on both readers. Xteink progress actions remain manual.
- **Optional library:** installs pinned Calibre-Web for an existing Calibre library, sets a generated administrator password before starting its LAN service, and preserves EPUB download bytes.

[Follow the complete device and setup guide](docs/SETUP.md). Software tests and a firmware build do not replace the guide's physical-device checkpoints.

## Compatibility

| Component | Integration reference |
| --- | --- |
| Mac | macOS; Python 3.10 or newer; authenticated GitHub CLI |
| Kindle | Paperwhite 5, firmware 5.19.2, already jailbroken, KOReader kindlehf build based on v2026.07.2 |
| Xteink | X4 Pro, pinned custom CrossPoint 1.6.5 source |

This device pair was used for integration testing. Other Kindle models require their own supported jailbreak and KOReader path. The wizard's full fresh-Mac/device walkthrough still needs the physical acceptance checkpoints in the guide; compilation and automated tests do not establish compatibility with every device.

## Preview, resume and diagnose

```sh
python3 setup.py --dry-run
python3 setup.py --help
python3 setup.py doctor
python3 setup.py status
```

Run the wizard again to resume skipped steps. Each component also has a subcommand; use `python3 setup.py COMMAND --help`. The wizard never erases books, factory-resets readers, or flashes a Kindle.

Reader Bridge keeps local data under `~/Library/Application Support/Reader Bridge`. The collector and optional library use ports 8084 and 8083; occupied ports are checked. Its own LaunchAgents are `com.readerbridge.collector` and `com.readerbridge.library`. An asleep Mac cannot receive uploads; devices retain their queues.

```sh
python3 setup.py uninstall
```

This removes only owned background services. Archives, local inboxes, backups, library books and device installations remain available.

## Existing highlights

KOReader's plugin imports modern annotations from books still in reading history. Open older annotated books once to let KOReader migrate their sidecars. You can also import an English Kindle export:

```sh
python3 setup.py --dry-run import-clippings "/path/to/My Clippings.txt"
python3 setup.py import-clippings "/path/to/My Clippings.txt"
```

Notes and bookmarks are excluded. Unsupported languages are skipped rather than guessed; the source export is never changed. Quotes are first acknowledged locally; `status` reports whether GitHub publication is still pending.

## Privacy and limits

### Wi-Fi and battery

Automatic highlights do not require an always-on Wi-Fi connection. Xteink connects to a saved network only when uploads are waiting, and switches the radio off afterwards if the sync task enabled it. An already-connected radio remains under its existing owner's control. Failed attempts back off from one minute to fifteen minutes; sleeping readers are not woken to upload. The KOReader plugin only uses an already-connected network and stops its work on suspend.

Uploads, retries and awake queue checks still consume some energy. Long-duration battery drain has not been measured; this is not a zero-overhead claim. Reading-progress sync and other network features have their own Wi-Fi settings.

### Data and scope

Use a trusted home LAN. Device highlight HTTP requests carry a dedicated bearer token without transport encryption. Do not forward these ports through your router or publish pairing files, queue files, backups, books or account exports.

The shared archive collects excerpts; it does not synchronize underlines between rendering engines. Deleting a quote permanently suppresses the matching normalized title, author and passage. There is no restore command yet, and deletion does not rewrite Git history or remove annotations from the other device.

Custom firmware is built from the source revision in [firmware.json](firmware.json), with PlatformIO 6.2.0 and SdFat 2.3.1. This project does not redistribute prebuilt firmware, jailbreak bundles, DRM tools or books. First builds require internet access and may take several minutes. [Upstream sources and packaging notes](docs/UPSTREAM-SOURCES.md).

## Development

```sh
python3 -m unittest discover -s tests -v
for test in koreader/sharedhighlights.koplugin/tests/*_test.lua; do lua5.1 "$test"; done
```

Tests use temporary files and mocked external commands; collector HTTP tests bind localhost. They never install live services, create a GitHub repository or modify a device. Reader Bridge's original code is MIT licensed; external applications retain their own licenses.
