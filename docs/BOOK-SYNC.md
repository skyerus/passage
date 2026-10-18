# Experimental Kindle book inbox

This optional local service imports a downloaded Kindle KFX book into the Mac's
Calibre library and returns one canonical EPUB to KOReader. It is separate from
the packaged Passage app and must be installed explicitly. Xteink background
delivery is not implemented; the resulting books are available through its
existing Home Books catalog when a working reader is available.

The Kindle must first receive the purchase in Amazon's normal interface. The
tested KOReader launcher stops Amazon background services while running, so
purchase delivery during KOReader use is **not guaranteed**. Return to Kindle
Home, connect Wi-Fi and finish downloading, then launch KOReader. Once KOReader
and the Mac are awake on the same trusted network, the inbox checks approximately
once a minute. USB storage mode and sleep pause the device side.

## Components

- `book_sync.py` serves an authenticated LAN inbox on port 8086 and uses an
  existing Calibre `ebook-convert` installation with KFX Input to convert
  **already decrypted** `.kfx-zip` exports. The device's separately installed
  `kfxdedrm-scriptlet/bin/run_cmd.sh` performs the export. Neither tool is bundled.
- `koreader/bookinbox.koplugin` runs exports and network operations in a child
  process. Suspend or close kills that process group, including the exporter;
  interrupted work retries later. It does not modify native Kindle files, launch
  services, update blockers, highlights, progress settings or firmware.
- The Mac journal tracks each ASIN, retries failures with backoff and imports
  once. Ready EPUBs are immutable. Both library import and device delivery verify
  hashes. Existing EPUBs are never silently replaced.

Not every Kindle format or protection version is supported. A failed export or
conversion is retained for diagnosis/retry; it is not renamed to EPUB or marked
delivered. Main KFX files are discovered under `/mnt/us/documents`, excluding
`.sdr` resources, after a 60-second stability delay. A complete Amazon download
is still required. Personal documents without a 10-character ASIN and non-KFX
books are outside this importer.

## Requirements

This is an advanced, optional source installation for a **jailbroken Kindle**,
not a feature available on an unmodified Kindle or through the Amazon website.

1. An already working [KOReader installation](https://github.com/koreader/koreader/wiki/Installation-on-Kindle-devices),
   with its `koreader` folder visible over USB and the ability to read an EPUB.
2. A separately installed [on-device KFX export tool](https://github.com/jadehawk/kfx-dedrm)
   whose `run_cmd.sh dedrm INPUT OUTPUT_DIRECTORY` command works on your firmware.
   Test its own instructions first. Passage does not install jailbreaks, export
   binaries, Amazon credentials or decryption keys.
3. [Calibre](https://calibre-ebook.com/download) with the
   [KFX Input plugin](https://www.mobileread.com/forums/showthread.php?t=291290),
   and an existing Calibre library containing `metadata.db`. This service uses
   `ebook-convert` and `calibredb`; Calibre-Web is optional for sharing its library
   with other readers. Close the Calibre desktop application during imports.
4. Python 3.10 or later on the Mac, plus the checked-out Passage source. This
   service is not installed by the current Passage app's setup flow.

The physical transfer was verified on a Paperwhite 5 (11th generation), firmware
5.19.2, with KOReader `v2026.07.2-185-gdcf6e3b42_2026-09-20_kindlehf`, Calibre 7.24
and KFX Input 2.34.2. This is one tested configuration, not a claim that every
Kindle, firmware, book format or newer protection version works.

## Manual pairing

Exit KOReader and connect the Kindle by USB. Back up its `koreader/settings`
directory and the Calibre library. Choose a new private service directory, for
example `~/Library/Application Support/Passage Book Inbox`; keep it outside the
source checkout. Do not replace an existing configuration or pairing token.

Generate a token locally with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`.
Put it in both configuration files below; do not include the token in a command
line, source commit, screenshot or support report. Replace all placeholder paths
and the example private address with your own. JSON paths must be absolute;
`~` is not expanded inside JSON.

Use a private service directory containing `config.json` with `token` (at least
32 random characters), absolute `converter`, `calibredb`, `calibre_config`, and
`library` paths. The library must already contain Calibre's `metadata.db`.
`calibre_config` should point to a dedicated configuration containing KFX Input.
If you use your normal Calibre configuration instead, keep its plugin settings
and files intact. On macOS its usual location is `~/Library/Preferences/calibre`.

```json
{
  "token": "PASTE_YOUR_GENERATED_TOKEN_HERE",
  "converter": "/Applications/calibre.app/Contents/MacOS/ebook-convert",
  "calibredb": "/Applications/calibre.app/Contents/MacOS/calibredb",
  "calibre_config": "/absolute/path/to/calibre-configuration",
  "library": "/absolute/path/to/Calibre Library"
}
```

Set the service directory's permissions to `700` and `config.json` to `600`.
Copy `book_sync.py` into the service directory so checkout changes cannot alter
an installed service. Test it in the foreground first:

```sh
python3 "/absolute/path/to/private/service/book_sync.py" \
  --state-dir "/absolute/path/to/private/service"
```

The default port is 8086. If it is occupied, select `--port PORT` and use that
port in the Kindle URL and login service too. An unauthenticated request to
`http://127.0.0.1:8086/v1/books` should return HTTP 401. The service uses HTTP on
the trusted LAN; do not forward this port through the router.

Before starting the service, register already converted books with
`--seed ASIN EXISTING_EPUB`; this copies and publishes their exact bytes without
reconversion or another Calibre import. Seed only EPUBs already in the shared
Calibre library. Back up that library and device settings first.

Install the plugin in the Kindle's `koreader/plugins` directory and create
`koreader/settings/bookinbox-config.json` with `url` (private LAN HTTP origin and
port), optional `fallback_url` (second private LAN origin), matching `token`,
`runner` (absolute on-device export script path), and
`books` (destination directory, typically `/mnt/us/Books`). Protect credentials
and keep the service on the trusted home network.

Optionally seed `bookinbox-state.json` with `downloaded` entries keyed by ASIN,
each containing the existing on-device `path` and matching canonical `sha256`.
An `ignored` map can record the existing native library at installation, leaving
only future downloads eligible for automatic import. Preserve these maps during
reinstallation. The manual **Tools → More tools → Sync purchased books** action
triggers the same queue immediately; it does not override ignored books.

Example `bookinbox-config.json` on the Kindle:

```json
{
  "url": "http://reading-mac.local:8086",
  "fallback_url": "http://192.168.1.20:8086",
  "token": "PASTE_THE_SAME_GENERATED_TOKEN_HERE",
  "runner": "/mnt/us/extensions/kfxdedrm-scriptlet/bin/run_cmd.sh",
  "books": "/mnt/us/Books"
}
```

The two URLs must identify the same Mac. A DHCP reservation keeps the fallback
address stable. If you have only an IP address, use it for `url` and omit
`fallback_url`. Create the Books directory if absent. Copy the entire
`koreader/bookinbox.koplugin` folder into the Kindle's `koreader/plugins` folder.

With no `bookinbox-state.json`, all supported downloaded KFX books are eligible
for import, including older purchases. To start with future purchases only,
create this file before launching KOReader and list the ASINs to skip:

```json
{"downloaded": {}, "ignored": {"B000000001": true, "B000000002": true}}
```

Those are synthetic examples; replace them with the IDs at the end of your
existing KFX filenames. Remove an ASIN from `ignored` while KOReader is closed
to import that book later. Do not remove entries from `downloaded` to retry an
upload, and do not replace existing state with this example during upgrades.

Safely eject and unplug the Kindle. Finish downloading a purchase in the native
Kindle interface, open KOReader, enable Wi-Fi, and leave the reader awake. Check
the new EPUB in Books; if the folder was already displayed, leave and reopen it
to refresh the listing. Confirm the transfer before enabling login startup.

## Start after Mac login

After the foreground test succeeds, stop that foreground service and create a
new `~/Library/LaunchAgents/com.passage.book-inbox.plist`. Use the full paths to
your Python executable and service directory in place of these placeholders;
property lists do not expand `~`. Do not overwrite a different existing job.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.passage.book-inbox</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/caffeinate</string><string>-s</string>
    <string>/absolute/path/to/python3</string>
    <string>/absolute/path/to/private/service/book_sync.py</string>
    <string>--state-dir</string><string>/absolute/path/to/private/service</string>
  </array>
  <key>WorkingDirectory</key><string>/absolute/path/to/private/service</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>Umask</key><integer>63</integer>
  <key>StandardOutPath</key><string>/absolute/path/to/private/service/service.log</string>
  <key>StandardErrorPath</key><string>/absolute/path/to/private/service/service-errors.log</string>
</dict></plist>
```

```sh
plutil -lint "$HOME/Library/LaunchAgents/com.passage.book-inbox.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.passage.book-inbox.plist"
launchctl print "gui/$(id -u)/com.passage.book-inbox"
```

The Mac must remain awake, logged in, reachable and unlocked after a FileVault
restart. `caffeinate -s` prevents idle system sleep on AC power; it does not make
a closed-lid or shut-down Mac reachable. An actual logout/login check is separate
from validating the property list or starting the job once.

## Verification and recovery

Test an actual owned purchase through download, export, upload, conversion,
Calibre listing, device delivery, and opening the resulting EPUB. A unit test,
installed plugin, or server health response does not establish physical success.
Confirm the EPUB hashes agree and existing books and reading positions remain.

Mac status is in private `books.sqlite3`; conversion output is in `logs/ASIN.log`.
Kindle status is in `bookinbox-result.json`; the Mac records the latest status in
`device-status.json` and checksum-verified acknowledgements in `deliveries`.
Raw exporter output is discarded because the tool prints device secrets.
Original purchases remain untouched. Do not share these
files publicly; they can contain book metadata and private paths.

To disable, exit KOReader, remove only the new `bookinbox.koplugin` directory,
and unload the dedicated Mac book-inbox LaunchAgent with
`launchctl bootout "gui/$(id -u)/com.passage.book-inbox"`. Move its property list
out of `~/Library/LaunchAgents` to keep it disabled at the next login.
Keep the canonical library,
originals, settings and journal until any wanted EPUBs are backed up. Re-enable
with the same pairing token and state to avoid duplicate work.
