# Reading-position sync inside Reader Bridge

The Mac app includes a private KOSync-compatible service. KOReader on Kindle and CrossPoint on Xteink use their existing **Progress sync** features to save their place to Reader Bridge. No public sync account, Docker installation, or hosting subscription is required.

## Connect once

1. In **Settings → Reading positions**, choose **Use Reader Bridge for positions**. Reader Bridge starts the service and creates a dedicated local account.
2. In **Setup → Reading positions**, close KOReader, connect Kindle in USB drive mode, and choose **Connect Kindle**. The app preserves its old settings, installs the Reader Bridge progress patch, and copies existing server positions for EPUBs on that Kindle. A current KOReader version with user patches enabled is required. It checks the old server before changing the account. Internet access is needed for this one-time copy if the old server is online.
3. On Xteink X4 Pro, open **File Transfer** on the same trusted network. Enter the shown address in Reader Bridge and choose **Connect Xteink**. Alternatively, connect its SD card and choose **Use its SD card instead**. No firmware change is needed if the reader already supports custom KOSync servers.
4. Eject Kindle and reopen KOReader. Restart Xteink so it loads the new settings. Keep the exact same EPUB bytes on both readers.
5. On Xteink, choose **More → Sync Progress → Upload Local**, then sync the same book in KOReader. Read onward in KOReader and close the book, then choose **Apply Remote** on Xteink. Confirm **The passage matched in both directions** in the app only after checking the actual text.

Reader Bridge preserves KOReader's existing automatic-sync preferences. New configurations enable Auto sync; the reader's own Wi-Fi settings still apply. CrossPoint's Upload Local and Apply Remote actions remain manual. Choosing a new server does not add a polling loop, keep the readers' Wi-Fi on, change their sleep settings, or create Amazon Whispersync compatibility.

## Daily use

The service starts after Mac login and stays running when you close the app. The Mac must be awake and reachable from the readers; it cannot sync during shutdown, FileVault unlock, sleep, or when the readers are away from its network. Readers retain their local reading place while offline. KOReader versions that support an offline sync queue retain it. Xteink can upload its local place once the Mac is reachable.

Automatic KOReader uploads carry the revision of the last position the reader acknowledged. If Xteink has changed that position, an older queued Kindle upload is rejected; reconnecting cannot silently replace the Xteink position. KOReader then checks the remote position using your existing sync preferences. A failed manual upload loses its override permission before being queued for later.

Reading backwards is supported. After accepting the remote position you can read or navigate in either direction. **Push progress from this device now** explicitly chooses the Kindle's current location, even when another device has changed the saved place. Xteink's **Upload Local** is likewise an explicit choice. Reader Bridge does not force the furthest percentage.

For existing installations from 0.6.0 or 0.6.1, install the newer app, restart position sync in Settings, and **Reconnect Kindle** once with KOReader closed. Eject and reopen KOReader to load the patch. No Xteink firmware change is needed. The server requires protected uploads from the paired Kindle even if its patch is later disabled; restore the patch instead of bypassing that protection.

Conflicting queued positions are preserved on Kindle in `koreader/settings/readerbridge-progress-state.lua` for recovery; they are not blindly retried. The normal offline queue removes entries only after the server acknowledges them or the patch preserves a conflict. Merely fetching a position without accepting it does not authorize an overwrite. If you want to retain your offline Kindle location instead, deliberately push it from KOReader. The service stores the exact position string and percentage supplied by each reader; the readers remain responsible for mapping that position to their layout.

**Settings → Reading positions** shows saved-book counts and actual upload receipts. A pairing file alone does not prove a reader has synced. Technical addresses are under **Settings → Advanced**. If the Mac's address changes, update it there and reconnect both readers. A router DHCP reservation helps keep a stable address.

## Backups and recovery

Automatic iCloud/folder snapshots include reading positions along with highlights, dates and covers. A snapshot containing positions uses backup format version 2 and requires Reader Bridge 0.6.0 or later to restore. Version 1 highlight-only snapshots remain supported. Credentials are excluded from snapshots; reconnect readers after restoring onto another Mac. Restore adds missing positions and preserves current ones.

Pairing saves old device configuration files in the Mac's private Reader Bridge backups directory before replacing them. Original book files and their local reading positions are not edited. Existing queued KOReader positions are merged using their recorded queue times, then removed from the old queue only after being stored locally; the old queue is backed up. Re-pairing the same local account preserves pending queue entries. Readers configured with different old accounts must be reconciled before automatic migration.

Turning off position sync stops its background job and retains the position database and credentials. It does not silently switch the readers back to a public server. Turn it on again to resume with the same account. Keep the app at its installed location because the background jobs use its bundled interpreter.

## Implementation and boundaries

The service implements authenticated `GET /users/auth`, `GET /syncs/progress/:document`, and `PUT /syncs/progress`, following the [KOReader client API](https://github.com/koreader/koreader/blob/master/plugins/kosync.koplugin/api.json). Reader Bridge adds opaque `reader_bridge_revision` tokens and an optional `metadata.reader_bridge` update condition; conflicts return HTTP 409. Its KOReader user patch activates only for the paired Reader Bridge endpoint and account. Device requirements and revisions persist across service restarts. Existing records gain revisions without changing their position or recorded time; restores issue fresh revisions. Authentication uses the existing `x-auth-user` and `x-auth-key` headers. Account creation is local to the app; network registration is disabled. It is a single-account service, not a public multi-user KOSync hosting product.

Requests use HTTP on the trusted LAN, like Reader Bridge's highlight connection. Do not expose the port to the internet or use it on an untrusted network. The dedicated generated password is unrelated to Amazon, GitHub, iCloud or the prior sync account. CrossPoint imports the provisioned password and rewrites it in its normal obfuscated format after restarting. Account credentials and request contents are not written to service logs.

Positions are durable SQLite records under `~/Library/Application Support/Reader Bridge/progress_sync`. The service normally uses port 8085, selecting another available port before pairing if necessary. The separate background job preserves compatibility with older highlight collectors already running on port 8084; the app manages both services.
