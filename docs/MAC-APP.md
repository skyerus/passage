# Passage for Mac

Passage collects your reading highlights in a searchable local library. Use a Kindle with KOReader, a supported CrossPoint reader, or both. Backups and reading-position sync are optional.

**Current release status:** there is no published signed, notarized Passage installer yet. The latest public v0.1.0 release is command-line source. These are the first-install instructions for the app package being prepared; download availability and physically accepted models must be stated in its release notes.

## Before you start

You need macOS 13 or later, a reader charging/data cable, and your Mac and reader on the same trusted home Wi-Fi. Use an ordinary DRM-free EPUB to test. Basic app setup does not require developer tools or a GitHub account.

For a Kindle, first complete a supported jailbreak and install KOReader. Follow the [KindleModding introduction](https://kindlemodding.org/jailbreaking/), [exact model and firmware picker](https://kindlemodding.org/jailbreak-wizard.html), and [KOReader Kindle installation guide](https://github.com/koreader/koreader/wiki/Installation-on-Kindle-devices). Complete the method's post-jailbreak steps. Open the test EPUB in KOReader before returning to Passage. If no method supports your Kindle, stop the pairing path; existing `My Clippings.txt` imports remain available.

For a CrossPoint reader, install CrossPoint for your exact hardware using the [official entry point](https://crosspointreader.com/) and [device picker](https://updates.crosspointreader.com/). Save a copy of the SD card, including `.crosspoint`, before a firmware update. Passage's matching custom image is also needed for automatic highlights; Setup offers it when this app package includes one. Select the exact model printed on your reader. Do not install an image for a similar-looking model.

## Download and open

1. In [Releases](https://github.com/skyerus/reader-bridge/releases), select a release containing a `.dmg` installer. Its notes must say which Mac architecture, OS versions, and physical reader models passed acceptance. Source-code ZIPs and `-development.dmg` files are for developers.
2. In **Apple menu → About This Mac**, a **Chip** such as Apple M1/M2/M3/M4 means choose **arm64**. An Intel **Processor** means choose **x86_64**.
3. Open the disk image. Drag **Passage** onto **Applications**, wait for copying, and eject the image in Finder.
4. Open **Applications → Passage**. Confirm macOS's normal downloaded-app prompt. Allow local-network and removable-volume access when Passage asks so it can reach and configure the selected reader. Allow its background service when macOS asks.

If macOS says the developer cannot be verified, or the app is damaged, stop and check the release's signing/notarization status. A consumer download should pass Gatekeeper normally; disabling Gatekeeper or deleting quarantine attributes is not an installation step.

Keep the app in Applications. Its background service uses the runtime inside it.

## Connect your reader

Choose **Set up your reader**, then answer **What will you read on?** with **Kindle**, **CrossPoint reader**, or **Both readers**. Select **Start Passage sync** when Setup reaches **Connect to your Mac**, then follow the next action shown. You can add another reader later. Existing verified installations offer **Use existing setup**.

**Kindle:** complete the prerequisite checklist, exit KOReader, then connect the Kindle in USB storage mode. Choose the detected Kindle and let Passage install its plugin and settings. Eject it safely, unplug, reopen KOReader, and enable Wi-Fi. Save a short highlight in your test book. Passage should show the quote and book in **Highlights**. The plugin uses an existing Wi-Fi connection; it does not enable Wi-Fi itself.

**CrossPoint:** select your exact **Model** and complete its prerequisite checklist. Connect its SD card or use its File Transfer mode as Setup directs. Leave **Prepare Passage firmware** selected when updating and choose **Prepare firmware and connect**. Passage verifies and stages the included application image without downloading compilers. Finish the device's own SD-card firmware-update action shown in Setup, then confirm **I installed it and see Sync Highlights**. Leave File Transfer mode, reopen the EPUB, save a clipping, and check it appears in Passage. Button and touch controls differ by model; follow that model's guide. An image being staged is not proof that the reader installed it.

The first highlight can also send the EPUB's original JPEG/PNG cover. A book without a supported embedded cover uses a placeholder. Keep the Mac awake and allow a brief upload attempt. If nothing arrives, use the reader's **Sync Highlights** action once, then check its Wi-Fi and Passage's status.

For two readers, repeat the highlight check on each. To continue at the same passage, enable the optional reading-position service and use the exact same EPUB file on both. Follow the [position-sync walkthrough](PROGRESS-SYNC.md), including a test in both directions. CrossPoint uses **Upload Local** when leaving and **Apply Remote** when returning. Choose **Finish setup for now** to leave positions for later; any existing position connections stay active. A single-reader archive does not need this service.

## Back up and use your library

In **Settings → Backup**, choose **Turn on iCloud backup** or **Another folder**. Passage saves a new snapshot when the archive changes. A saved folder copy and a completed iCloud upload are different: Finder shows cloud upload status. Backups include highlights, recorded dates, notes, deletion history, cached covers, and local reading positions. They exclude passwords, pairing tokens, and EPUB books.

Use **Highlights** to browse by book, search, and copy a quote. Its archive menu imports `My Clippings.txt`, supported Kindle JSON, and Passage exports; **Export highlights & covers** creates a portable JSON archive. Right-click a book to change its cover using an image or the book's EPUB. Export does not include private connection credentials.

The collector continues after you close the window or quit Passage and starts after Mac login. The app's **Open at login** setting controls whether its window also opens. The Mac can sleep normally; it cannot receive uploads while asleep. Readers keep pending changes and retry when connected. Keep the Mac awake for initial setup and tests.

Restore with **Settings → Backup → Restore a backup**, using a downloaded `.readerbridge` snapshot. Restore merges missing records and artwork, preserves existing edits and deletions, and saves a local recovery snapshot first. A new Mac still needs fresh reader pairing. Earlier backups and Git history can retain previously deleted text.

## Upgrading Reader Bridge

Back up or export your archive first, then quit the app. For a fresh Passage installation, replace the app in Applications at the same location. Keep `~/Library/Application Support/Reader Bridge`; it contains your existing library and pairing state.

An earlier Reader Bridge installation may run its background service from a different app location or filename. Replace the app at that existing location and retain the filename **Reader Bridge.app** for this upgrade so its configured runtime path remains valid. Do not delete or move the original runtime while its service still uses it. The display name becomes Passage, while the application identifier, data directory, service labels, and reader connections remain compatible.

If the app offers **Use existing setup**, it checks the earlier service's ownership and authenticated response before connecting. Keep the original service's settings; Passage does not take control of unrelated listeners. Reinstall the updated Kindle plugin and matching reader firmware when release notes require it, preserving queued changes and `.crosspoint` settings.

## If setup pauses

Check the Mac is awake and logged in, the reader is using the same Wi-Fi, and macOS allows Passage's network access. Guest networks can isolate devices. Reconnect a USB device or leave and re-enter File Transfer mode when requested. A saved pairing describes configuration; it does not prove that a sleeping or unplugged reader is online.

If Passage reports an occupied port, use an unused one in **Connection settings** before first pairing. It leaves an unknown service alone. For an existing paired setup, keep the original address and port or deliberately reconnect the readers after changing them. Do not erase books, reset a reader, or delete offline queues to solve a connection problem.

Keep pairing files, archives, and diagnostic logs private. Highlight requests use a dedicated token over HTTP on your LAN; use a trusted network and do not forward service ports through the router. Support reports should contain redacted status only.

GitHub backup and a Calibre-Web book catalog are advanced optional services with their own account or dependency setup. See the [command-line guide](SETUP.md) and [maintainer build/release guide](RELEASING.md). They are not required for the basic highlight archive.
