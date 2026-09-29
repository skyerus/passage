# Set up Reader Bridge on a Mac

Reader Bridge collects Kindle KOReader highlights and Xteink CrossPoint clippings in your own archive. It can also help connect both readers to a home book library and the same reading-progress account.

These are three separate services:

| Feature | Where it lives | What you should expect |
| --- | --- | --- |
| Shared highlights | Your Mac collector, then your chosen private GitHub archive | Both readers contribute quotes to one collection. An underline on one reader does not appear inside the book on the other. |
| Reading progress | Your account at `https://sync.crosspointreader.com` | The devices can return to the same passage. CrossPoint still needs a manual progress-sync action. |
| Home Books | Calibre-Web on your Mac | Both readers download the exact same EPUB from one library. Downloaded books remain readable offline. |

## Before starting

Have the Mac, both readers, charging cables, and one ordinary DRM-free EPUB ready. Use a book you are allowed to copy to both devices. Keep the Mac plugged in, awake, logged in, and on the same trusted home network as the readers.

Configuration reference checked on **2026-09-29**: the development setup used a **Kindle Paperwhite 5 (11th generation), firmware 5.19.2**, already jailbroken, running **KOReader v2026.07.2-185-gdcf6e3b42_2026-09-20_kindlehf**, plus an **Xteink X4 Pro with the custom CrossPoint 1.6.5 build**. This is a tested configuration reference, not a compatibility guarantee for another Kindle or firmware. A successful software build is also not proof that every device has completed the checks below.

Back up the readers before modifying them. Include the Kindle's `koreader` directory and book sidecar folders, and the Xteink SD card's hidden `.crosspoint` directory. Pairing files and queues are private: do not upload them to an issue or the public Reader Bridge repository.

## 1. Get KOReader working on the Kindle

Skip installation if KOReader already opens and reads your EPUB.

1. In Kindle **Settings → Device options → Device info**, record the exact model and firmware. Follow the [KindleModding introduction](https://kindlemodding.org/jailbreaking/), then its [Find My Jailbreak wizard](https://kindlemodding.org/kindle-models). Complete its compatibility questions and the method it selects, including its post-jailbreak and update-blocking steps. **Stop if it reports no supported method.** Reader Bridge does not jailbreak or downgrade a Kindle.
2. Follow the matching path in the [official KOReader Kindle installation guide](https://github.com/koreader/koreader/wiki/Installation-on-Kindle-devices). Modern jailbreaks may provide KPM. When the guide confirms KPM applies, enter these commands separately in the Kindle search bar, waiting for each to finish:

   ```text
   ;kpm update
   ;kpm upgrade
   ;kpm install koreader
   ```

   Open the resulting KOReader launcher document. For manual installs, use the package and launcher prescribed by that guide; firmware 5.16.3 and later uses `kindlehf`. Do not mix instructions from different jailbreak methods.
3. Open your test EPUB in KOReader, turn a page, close the book, and exit KOReader.

**Checkpoint:** KOReader launches and reads the EPUB. The stock Kindle reader is not the reading app used by this bridge. KOReader does not read DRM-protected books or KFX. Exit KOReader before connecting its USB storage.

## 2. Prepare the Xteink X4 Pro

If CrossPoint is not installed, start with the [official CrossPoint site](https://crosspointreader.com/) and its device-specific installation instructions. Select **X4 Pro**, not X4 or X3. Stop if the installer does not explicitly support your model.

**Checkpoint:** The device is confirmed as an X4 Pro, CrossPoint starts, and it can open your EPUB. Install the custom highlights build during the Xteink pairing step below; you do not need to build it before running the Mac wizard.

## 3. Run the Mac setup wizard

Download or clone the public `skyerus/reader-bridge` source, open Terminal in that folder, and run:

```sh
python3 setup.py
```

The wizard guides the remaining steps. To inspect prerequisites without changing anything:

```sh
python3 setup.py doctor
```

Preview the guided setup before applying changes:

```sh
python3 setup.py --dry-run
```

Select or create **your own private GitHub archive repository** when asked. This is separate from the public Reader Bridge source repository. Use your own GitHub login. Do not select another person's quotes repository, and do not put tokens in commands, screenshots, or issue reports.

Reader Bridge keeps its local state under `~/Library/Application Support/Reader Bridge`. Its collector uses port **8084**. The collector and optional library start after you log in to the Mac; they cannot serve devices while the Mac is asleep, shut down, or waiting for FileVault unlock.

**Checkpoint:** `python3 setup.py status` reports a healthy collector and pending publication counts. The wizard shows the Mac's LAN address and next pairing step. Never use `localhost` as the address on a reader: that means the reader itself.

## 4. Pair the readers for highlights

### Kindle

Exit KOReader, connect USB, and select the mounted Kindle in the wizard. For a typical mount, the equivalent command is:

```sh
python3 setup.py kindle --mount /Volumes/Kindle
```

The installer adds the Shared highlights plugin and its pairing configuration. Existing device identity and queued changes must survive a reinstall. Eject the Kindle safely and reopen KOReader.

Open a book, highlight a short unique sentence, then use **Tools → More tools → Shared highlights → Sync highlights** once to check the connection. Menu placement can vary with the KOReader build. With Wi-Fi already connected, later highlights upload automatically. The plugin does not turn Wi-Fi on by itself; offline work stays queued. When upgrading an older installation, open each existing annotated book once so the plugin can establish its deletion baseline.

### Xteink

Reader Bridge highlights require its custom CrossPoint firmware. Stock CrossPoint compatibility alone does not provide the shared-highlights uploader. The installer identifies the target model, builds the pinned CrossPoint source locally with PlatformIO in an isolated environment, then stages the resulting application firmware. Allow extra time and internet access for compiler and dependency downloads. This release provides source rather than a public prebuilt binary; redistribution of every bundled binary dependency has not been verified.

For an SD-card update, use the installer's locally built **application firmware** with **Settings → System → SD Card Firmware Update**. Follow the installer's printed instructions for the filename/location and complete the update on the reader itself. Do not write an application-only binary to flash address zero. Preserve the SD card and hidden `.crosspoint` directory; it contains settings, clippings, and pending uploads.

**Firmware checkpoint:** CrossPoint starts, reports the intended custom version, opens the EPUB, and offers **More → Save Clipping**, **View Clippings**, and **Sync Highlights**.

Choose the X4 Pro pairing step in the wizard. Use its current private IP while it is in File Transfer mode, or pair through its mounted SD card. The model must be explicitly `xteink_x4_pro`; follow the wizard's firmware prompt if upgrading is required.

The pairing file is `/.crosspoint/highlight-sync.json`. It contains a dedicated token and the Mac collector endpoint, such as `http://192.168.1.20:8084/v1/highlights`. Use the generated values. The token is distinct from your library and progress passwords.

Leave File Transfer mode and open a book. Tap the center, choose **More → Save Clipping**, drag over text, and release to save. The reader quietly attempts uploads from Home or the normal reader using a saved Wi-Fi network. Failed attempts back off; sleeping readers do not wake just to sync. **More → Sync Highlights** is available to test immediately.

**Checkpoint:** Find one new test quote from each reader in the collector's chosen archive. Check the full excerpt and title, then restart the Mac service and confirm those quotes remain. A successful local receipt and a successful GitHub publication are separate checks.

## 5. Add the home book library

This step needs an existing **Calibre library folder containing `metadata.db`**, not just a folder of EPUBs. Prepare it with [Calibre](https://calibre-ebook.com/download_osx) if needed, then use the wizard's library step or:

```sh
python3 setup.py library --books "/path/to/Calibre Library"
```

The installer uses Calibre-Web on port **8083**. It initializes the application without starting a server, sets a generated private administrator password, disables anonymous access and public registration, then starts the configured LAN service. The wizard prints the local file containing your administrator credentials; keep it private. Sign into the web interface and create a separate account allowed to browse/download books. See [Calibre-Web's upstream documentation](https://github.com/janeczku/calibre-web) for the application settings.

The installer turns off metadata embedding into downloaded EPUBs; keep that setting disabled. Use the same unmodified download on both readers; reconversion or metadata rewriting can change its binary identity.

Add the catalog URL printed by the wizard to KOReader's **OPDS catalog** and CrossPoint **Settings → System → OPDS Servers → Add Server**. Name it **Home Books**, and use the download account on each reader. Download the same test EPUB on both.

**Checkpoint:** Each reader browses Home Books with its credentials and downloads the EPUB. A browser without credentials must not be able to browse the library. If `.local` discovery fails, use the Mac's private IP; a router DHCP reservation prevents that address changing unexpectedly.

## 6. Connect reading progress

Run the wizard's progress step (`python3 setup.py progress`) for its device checkpoints. Use a unique progress-only username and password, separate from GitHub, Amazon, the book library, and the highlights token.

1. On CrossPoint, open **Settings → System → KOReader Sync**. Set the server to `https://sync.crosspointreader.com`, enter your chosen credentials, and **Sign Up** once. Select **Ask every time** for Sync Behavior.
2. With the test EPUB open in KOReader, open **Progress sync**. Set that same custom server and log into the same account. Enable **Auto sync** and use **Binary** document matching. [KOReader's progress guide](https://github.com/koreader/koreader/wiki/Progress-sync) describes these options.
3. Read to a distinctive paragraph on CrossPoint. Open **More → Sync Progress → Upload Local** before leaving it.
4. Open the identical EPUB in KOReader with Wi-Fi connected; sync if needed. Confirm the paragraph matches, allowing for a different page layout.
5. Read onward in KOReader and close the book so auto sync can send its position. On CrossPoint choose **More → Sync Progress → Apply Remote**. Confirm the new passage.

**Checkpoint:** Both directions work on the same EPUB. Do not use percentage equality as the only test. **Upload Local** sends the Xteink position; **Apply Remote** takes the server's position. CrossPoint Smart sync prefers the furthest completion, which can be wrong when you intentionally reread earlier text. [CrossPoint progress instructions](https://github.com/skyerus/crosspoint-reader/blob/77b30d58e260ce5405234f84fe240833b726df9d/USER_GUIDE.md#367-koreader-sync-quick-setup).

## Daily use and limits

- **Highlights:** Keep reading offline; uploads resume when the Mac and reader are reachable. KOReader needs Wi-Fi already connected. Xteink can try a saved network while awake in Home/reader. Highlights remain stored on the reader after a successful upload.
- **Long Xteink selections:** While dragging, hold at the bottom or right edge for about one second to turn forward, or top/left to turn back. Move out of the edge zone before turning again. Release to save. Selection can span pages within one chapter/spine item. It stops at 4 KiB of complete UTF-8 words and stores the actual captured endpoint. There are at most 256 clippings per book.
- **Delete deliberately:** A deletion sends a permanent archive tombstone for the matching title, author, and passage after normalization. Stale uploads and later Amazon refreshes cannot resurrect that quote; highlighting exactly the same passage again does not restore it. There is no restore command in this version. It does not remove an annotation from the other device or erase Git history, backups, or previously sent messages.
- **Progress:** Manually Upload Local when leaving Xteink and Apply Remote when returning. The Mac does not host the default progress server; internet access is still needed for that service.
- **Existing Amazon highlights:** The optional `import-clippings` command imports English-format highlights from a `My Clippings.txt` file you supply. It is separate from KOReader capture. Keep Amazon account data and purchased book files out of the public repository.

## If something does not connect

Run `python3 setup.py doctor` and `python3 setup.py status`. Check the Mac is awake and logged in, devices use the same home LAN, the address is current, and the firewall allows the selected local services. Guest Wi-Fi often isolates devices. Do not expose ports 8083 or 8084 through your router.

The default highlights endpoint uses plain HTTP on a private LAN; its token is not encrypted in transit. Use a trusted network. Do not send the pairing files or full service state to support. Share only redacted diagnostic output.

Do not reset the Kindle, erase the Xteink SD card, or delete `.crosspoint` to fix a connection problem. Preserve queues, archive data, and backups first. Reinstalling should keep existing identities and pending work. Before uninstalling, export/back up the archive and keep the device queues until you have confirmed every wanted quote is stored.

## Optional reading comfort: fonts and dictionaries

These additions are separate from sync; install them after the basic setup works.

- **KOReader fonts:** copy licensed `.ttf`/`.otf` font files into `koreader/fonts/` on the mounted Kindle, preferably in a named subfolder, then restart KOReader and select the font in a book. [Lexica Ultralegible](https://github.com/jacobxperez/lexica-ultralegible/tree/release) is one optional font family. Preserve its license and keep existing fonts.
- **Dictionaries:** use KOReader's dictionary downloader or its [dictionary documentation](https://github.com/koreader/koreader/wiki/Dictionary-support). For the pinned CrossPoint build, supported StarDict dictionaries belong in `/dictionaries/<Dictionary Name>/` on the SD card. Follow the [pinned CrossPoint dictionary guide](https://github.com/skyerus/crosspoint-reader/blob/77b30d58e260ce5405234f84fe240833b726df9d/docs/dictionary.md); keep the `.ifo`, index and dictionary data files together and choose the dictionary on the device. Check a lookup before relying on it.

Reader Bridge does not bundle fonts, dictionaries, Kindle system files or books.
