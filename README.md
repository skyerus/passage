# Passage

<img src="docs/images/passage-icon.png" alt="Passage open-book icon" width="96">

Keep your Kindle and Xteink highlights in one Mac library. Passage collects passages from Kindle with KOReader and CrossPoint readers, with book covers, search, and optional iCloud Drive or folder backup. Use one reader, several, or import an existing Kindle highlights file.

Formerly Reader Bridge. Existing archives and reader connections keep their identities.

[Download for Apple Silicon](https://github.com/skyerus/reader-bridge/releases/download/v0.7.0-rc.2/Passage-0.7.0-arm64.dmg) · [Get started](docs/MAC-APP.md) · [Get help](SUPPORT.md)

**Passage 0.7.0 release candidate 2** is a Developer ID signed, notarized download for Apple Silicon Macs (M1 or later), requiring macOS 13 or later. It is a **pre-release** for testing; the separate clean-Mac walkthrough and physical-reader acceptance of this exact installer remain open. Read the [release notes and checksums](https://github.com/skyerus/reader-bridge/releases/tag/v0.7.0-rc.2). Intel Macs can build from source; no Intel, Windows, or Linux consumer installer is available.

![Passage book library with sample highlights and covers](docs/images/mac-books-dark.png)

## What you can do

- Collect highlights from one reader or several, including their recorded dates and embedded book covers.
- Search, copy, import an existing Kindle `My Clippings.txt`, and export a portable archive. Importing needs no jailbreak or reader pairing.
- Back up automatically to iCloud Drive or another folder. A GitHub account is optional.
- Sync reading progress to continue at the same passage on another reader, using the optional reading-position service and identical EPUB files. CrossPoint uses **Upload Local** and **Apply Remote**.

Your library is stored on your Mac; backups go to the destination you choose. The collector starts after login and continues when you close the window. The Mac must be awake and reachable for uploads; readers retain their offline queues.

Shared highlights are a quote collection. Each reader retains its own in-book underlines. Amazon's stock Kindle reader and Whispersync are separate: use KOReader for automatic Kindle capture, or import an updated Clippings export for stock-reader highlights.

## Before connecting a reader

**Kindle:** it must have a supported jailbreak and working KOReader. Read [KindleModding's introduction](https://kindlemodding.org/jailbreaking/), check your exact model and firmware with [Find My Jailbreak](https://kindlemodding.org/jailbreak-wizard.html), and follow the [official KOReader Kindle installation guide](https://github.com/koreader/koreader/wiki/Installation-on-Kindle-devices). Complete the guide's post-jailbreak steps and open an EPUB in KOReader before pairing. Passage does not jailbreak or downgrade a Kindle. If the wizard has no supported method for yours, you can still import an existing Clippings file.

**CrossPoint reader:** install CrossPoint for your exact model using its [official installation guide](https://github.com/crosspoint-reader/crosspoint-reader#install-firmware) and [flash tools](https://crosspointreader.com/#flash-tools). Passage then stages its matching custom firmware to collect highlights. Select your exact model in Setup and preserve your books and hidden `.crosspoint` folder when updating.

Factory USB-locked Xteink units need the upstream [locked-device and recovery guidance](https://github.com/crosspoint-reader/crosspoint-reader#usb-locked-devices-xteink-unlocker) before any custom update. Passage images have not been tested on factory-locked hardware; confirm image compatibility and recovery with that guidance first.

Use your Mac and readers on the same trusted home network, with DRM-free EPUBs. A second reader, reading-position sync, and a Calibre-Web catalog are optional. To collect stock Kindle highlights instead, open **Highlights → ⋯ → Import highlights** and choose `My Clippings.txt`.

## Install the Mac app

1. Download [Passage-0.7.0-arm64.dmg](https://github.com/skyerus/reader-bridge/releases/download/v0.7.0-rc.2/Passage-0.7.0-arm64.dmg) for your Apple Silicon Mac.
2. Open it, drag **Passage** into **Applications**, and eject the disk image.
3. Open Passage from Applications. Follow **Set up your reader** for automatic capture, or choose **Highlights → ⋯ → Import highlights** for an existing archive. Basic setup uses the bundled runtime and firmware; it needs no Terminal, Python, Git, compiler, or GitHub account.
4. Check your imported highlights appear. For a paired reader, save one new highlight with Wi-Fi connected and check it arrives in Passage.

[First-install walkthrough, backups, upgrades, and troubleshooting](docs/MAC-APP.md).

## Compatibility and privacy

The firmware bundle has compiled profiles for **Xteink X3, X4, X4 Pro, X4 Classic (X4C), Seeed reTerminal Sticky, and M5Stack Paper Mono**. These profiles route setup and firmware to the exact hardware. Compilation is separate from physical acceptance: previous live integration used a **Kindle Paperwhite 5 with KOReader and an Xteink X4 Pro**. Other models have not been physically tested here. The [Mac guide](docs/MAC-APP.md#reader-profiles) records this distinction.

Passage preserves settings, reader identities, queued highlights, and archive formats across upgrades. Local data remains in `~/Library/Application Support/Reader Bridge`; see the [upgrade instructions](docs/MAC-APP.md#upgrading-reader-bridge) before changing an existing app's location.

Highlight connections use a private LAN address and a dedicated bearer token over HTTP. Keep them on a trusted network; do not forward service ports through your router. Pairing files and backups are private. [Security policy](SECURITY.md).

## Development

[Contribute](CONTRIBUTING.md) · [Build and release the app](docs/RELEASING.md) · [Advanced command-line setup](docs/SETUP.md) · [Validation history](docs/VALIDATION.md) · [Upstream sources and notices](docs/UPSTREAM-SOURCES.md)

```sh
python3 -m unittest discover -s tests -v
swift test --package-path desktop
python3 scripts/build-macos.py --dmg
```

Development disk images are labeled `-development` and are signed ad hoc by default. Signed release candidates record remaining acceptance work; stable releases also require a separate clean-Mac and physical-reader acceptance report. Firmware packages include pinned application images, corresponding source, and dependency notices. No jailbreak tools, KOReader itself, books, fonts, or dictionaries are bundled.
