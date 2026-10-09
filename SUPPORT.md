# Getting help with Passage

Start with the [Mac setup and upgrade guide](docs/MAC-APP.md). The [release notes](https://github.com/skyerus/passage/releases/tag/v0.7.0-rc.3) identify the download, compiled reader profiles, and remaining physical tests. A saved pairing records configuration; a received highlight confirms the reader reached your Mac.

For missing highlights, keep the Mac awake and logged in, put the reader on the same trusted Wi-Fi, and try **Sync Highlights** once. KOReader needs Wi-Fi already connected. Leave CrossPoint File Transfer before reading and syncing. Guest Wi-Fi can isolate devices. Keep offline queues, book sidecars, and `.crosspoint` intact.

For a paused service, check Passage's status and the displayed error. An occupied port can be changed in **Connection settings** before pairing; existing readers need their saved endpoint updated if you change it later. For import-only use, choose **Highlights → ⋯ → Import highlights**, then **Start Passage & choose file…** to prepare the archive without a reader. Source/CLI users can run `python3 setup.py doctor` and `python3 setup.py status`.

If the problem remains, [open a bug report](https://github.com/skyerus/passage/issues/new?template=bug_report.md). Include Passage's version/build or release tag, macOS version and Mac chip, exact reader model and firmware, KOReader/CrossPoint version, the setup step, and what you expected. Use a short synthetic excerpt to reproduce it. Redact screenshots and brief errors; do not attach quotes, books, databases, pairing files, tokens, account details, or device backups.

For jailbreak or KOReader installation problems, follow [KindleModding](https://kindlemodding.org/jailbreaking/) and the [KOReader installation guide](https://github.com/koreader/koreader/wiki/Installation-on-Kindle-devices). For upstream CrossPoint installation, use its [official guide](https://github.com/crosspoint-reader/crosspoint-reader#install-firmware). Report problems with Passage's supplied plugin or custom firmware here, including the exact model.

Report security vulnerabilities through [private security reporting](https://github.com/skyerus/passage/security/advisories/new), following the [security policy](SECURITY.md).
