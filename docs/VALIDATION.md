# Validation for the initial source release

Automated checks cover collector receipt durability, retries, deletion propagation, concurrent publication, setup preview, private URL validation, queue and identity preservation, device model gates, upload readback, archive/port guards, LaunchAgent ownership recovery, partial library initialization, clippings parsing, and source-build override rejection. Plugin tests cover lifecycle, subprocess cancellation, queue races, and deletion behavior.

A fresh isolated Calibre-Web 0.6.27 setup was exercised through `Bridge.library` using a disposable library: generated administrator credentials, disabled anonymous browsing/public registration/metadata embedding, unauthenticated OPDS returning 401, and authenticated OPDS returning 200. Repeating the library setup preserved the generated administrator credentials. The smoke test substituted a temporary loopback server for LaunchAgent registration and did not change existing services.

The guide identifies the device pair used during integration. A complete fresh-Mac wizard, macOS reboot/login lifecycle, and new-device physical installation are separate acceptance checks. Follow the guide's checkpoints rather than treating these automated results as proof of every device configuration.

The installer's firmware build also completed in a fresh scratch application directory with its own PlatformIO installation and downloaded toolchain. It checked out the pinned source, initialized submodules, applied the SdFat 2.3.1 pin and produced the X4 Pro application image. This validates the build path; it does not mean that this separate smoke-test image was installed on a device.

Upstream was rechecked on 2026-09-29: the firmware source includes CrossPoint's current `develop` commit `d1509d0735bd0b7832c6765e2aa83e1f0c008eff`; the latest stable release at that check was 1.6.5. The custom firmware leaves the upstream Home activity and themes unchanged. Long-duration battery testing has not been performed.

## Automatic cover delivery candidate (2026-10-01)

The automatic-cover implementation is available in development builds. Physical
first-highlight and original-colour delivery passed on both readers; offline
device recovery checks and a new firmware source pin remain pending. It is not included in
the old firmware revision currently recorded in `firmware.json`; do not publish
an app release until that pin and the device acceptance are complete.

Verified in isolated fixtures: 102 Python tests, 25 Swift tests, seven Lua suites,
and the packaged app's real launchd/HTTP smoke test. Tests cover first-highlight
artwork with an empty catalog, UTF-8 metadata, malformed image/ack rejection,
retry fairness, cancellation, restarts, duplicate delivery, retained cover
identity, manual override and portable export. CrossPoint was reconciled with
upstream develop `664528b2` and the existing highlight branch. Its X4 Pro build
and 480 host tests passed. Those results do not substitute for physical device
networking, image extraction, suspend or battery measurements.

Physical first-highlight delivery was observed from a Kindle Paperwhite 11th
generation running KOReader and an Xteink X4 Pro: separate previously unseen
test books appeared with their source, quote, date and cover without manual
Sync or artwork import. The Xteink cover matched the embedded JPEG byte for
byte. This test exposed a KOReader bug: screen rendering converted its cover
to grayscale. The plugin now uses the engine's raw cover bytes instead;
regression tests cover JPEG/PNG pass-through, bounded copying, ownership and
failure cleanup. After reinstalling the corrected plugin and reopening the
highlighted book, the Kindle automatically delivered the original colour JPEG.
Both readers' received images matched their embedded EPUB cover byte for byte
(104,775 bytes); the app displayed the colour artwork. No desktop cover import
or manual device Sync was used. The Kindle test's old grayscale cover metadata
and its artwork acknowledgement were reset before retesting; its highlight
and all other archive entries were preserved.

Device release gate: on each updated reader, highlight in a separate book absent
from the Mac's archive. Observe the source-tagged quote and its embedded artwork
in Reader Bridge, without desktop artwork import or manual Sync. Repeat an
offline/restart/reconnect case, and confirm another highlight does not resend
the acknowledged cover. Preserve device settings and offline queues during
installation. Only after these checks should the tested firmware commit replace
the old source pin and the final installer be rebuilt.

## Combined Mac app with iCloud backup (2026-10-01)

The combined 0.5.0 development app preserves the colour-cover delivery code
tested on both readers and adds iCloud Drive or folder snapshots alongside the
optional GitHub archive. The suite passes 111 Python tests, 26 Swift tests and
seven Lua suites. A combined restore test checks that the original cover bytes
and highlight date appear in the restored app and in its portable export.
The packaged smoke test checks automatic snapshots, backup-worker restart,
cover upload and safe restore without resurrecting deleted quotes.

A disposable snapshot containing only synthetic text was written to iCloud
Drive; macOS reported the file uploaded with no upload error. The test file and
its dedicated cloud folder were removed afterward. The app reports a successful
folder save separately from cloud upload, which is managed by macOS. This is a
local development build, not a notarized public release; the remaining firmware
acceptance checks above still apply to a fresh-device installer release.

## App-hosted reading positions (2026-10-02)

The 0.6.0 development app includes a single-account KOSync-compatible service,
reversible reader pairing, and reading positions in version 2 iCloud/folder
snapshots. The suite passes 125 Python tests and 28 Swift tests. Tests exercise
authenticated HTTP exchange in both directions, intentional rereading, durable
storage, old-server and offline-queue migration, filename-to-binary matching,
different-account rejection, credential exclusion and restoration that retains
current positions. Migration records do not count as device upload receipts.

The packaged runtime passed the macOS acceptance script with disposable launchd
jobs and reader fixtures: real HTTP upload/download, service restart with the
same account and positions, startup configuration, fixture pairing with retained
highlight queues, version 2 snapshots, safe restore and shutdown with retained
data. Native Settings layout and the new position controls were inspected in
the development build. These tests do not establish a physical Kindle/Xteink
round trip, an actual Mac reboot, or measured battery usage. The physical
two-reader checkpoint in `PROGRESS-SYNC.md` remains required before confirming
setup. The firmware and notarization release gates above remain unchanged.

## Stale position protection (0.6.2, 2026-10-02)

The original physical test confirmed both directions but exposed a conflict:
Xteink uploaded a position, then a late Kindle upload replaced it. Repeating
with Kindle already awake avoided the race; it did not fix it.

The revision guard rejects that stale update, preserves the remote location
and ownership, and retains the conflicting Kindle position for recovery.
Tests cover same-second updates, concurrent writes, restart persistence,
legacy queued updates, deliberate backward reading, explicit overrides,
failed manual pushes losing override permission, rejected pulls, and queue
changes while an asynchronous upload is running. The patch adds no Wi-Fi
polling or sleep-setting changes.

Validation includes the Python/HTTP suite, Lua guard tests, Swift tests, and
`scripts/check-koreader-progress.lua` run against the connected Kindle's
actual KOSync `main.lua` and `KOSyncClient.lua`. That harness substitutes
network and UI boundaries; it does not claim a physical wake/sleep test.
Run it with:

```sh
lua scripts/check-koreader-progress.lua koreader/patches/2-reader-bridge-progress.lua /path/to/koreader/plugins/kosync.koplugin
```

The packaged macOS smoke test also sends a stale update over real HTTP to
its disposable paired background service and requires HTTP 409 with the
Xteink location retained. Physical wake/reconnect confirmation remains a
separate checkpoint after the new app and Kindle patch are installed.

The local installation check also exposed an upgrade boundary: ownership checks
must authenticate the previous service before requiring its new revision-guard
capability. The local app replacement also waits for the stopped service
port to be fully released before starting it again. Existing port guards
continue to reject unknown listeners and ports reserved by another process.
The packaged smoke test includes upgrading an owned service that advertises
the older health contract before pairing the guarded reader.
