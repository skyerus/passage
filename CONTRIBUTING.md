# Contributing to Passage

For a setup problem, use the [support guide](SUPPORT.md). For a proposed behavior or reader profile, [open an issue](https://github.com/skyerus/reader-bridge/issues/new) describing the user problem, exact hardware, and expected result. Physical testing is especially useful: include the exact app release, macOS version, reader firmware, and steps you observed, using synthetic books and quotes.

Create a branch or worktree from the current remote default branch. Keep changes focused and preserve existing data paths, reader identities, pairing tokens, offline queues, and archive compatibility. Reader support is defined by the modular profiles in [firmware.json](firmware.json); adding a model requires verified source routing and its own physical acceptance before claiming it tested. Firmware build output belongs in release artifacts, rather than Git.

Run the checks affected by your change:

```sh
python3 -m unittest discover -s tests -v
swift test --package-path desktop
for test in koreader/sharedhighlights.koplugin/tests/*_test.lua; do lua "$test"; done
for test in koreader/progress-tests/*_test.lua; do lua "$test"; done
```

Swift and app packaging require macOS; Lua tests use Lua 5.1. See [building and releasing](docs/RELEASING.md) for packaged runtime and firmware checks. Documentation changes need correct links and claims checked against the current release; an automated test or compiled image is separate from a physical device result.

In your pull request, explain the trigger, resulting behavior, checks run, and any remaining limits. Use synthetic fixtures. Do not commit credentials, pairing/queue files, personal paths, private archives, books, quotes, certificates, or signing keys. Keep third-party source and notices attached to distributed firmware. See the [security policy](SECURITY.md) for private vulnerability reports.
