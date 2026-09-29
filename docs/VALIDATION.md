# Validation for the initial source release

Automated checks cover collector receipt durability, retries, deletion propagation, concurrent publication, setup preview, private URL validation, queue and identity preservation, device model gates, upload readback, archive/port guards, LaunchAgent ownership recovery, partial library initialization, clippings parsing, and source-build override rejection. Plugin tests cover lifecycle, subprocess cancellation, queue races, and deletion behavior.

A fresh isolated Calibre-Web 0.6.27 setup was exercised through `Bridge.library` using a disposable library: generated administrator credentials, disabled anonymous browsing/public registration/metadata embedding, unauthenticated OPDS returning 401, and authenticated OPDS returning 200. Repeating the library setup preserved the generated administrator credentials. The smoke test substituted a temporary loopback server for LaunchAgent registration and did not change existing services.

The guide identifies the device pair used during integration. A complete fresh-Mac wizard, macOS reboot/login lifecycle, and new-device physical installation are separate acceptance checks. Follow the guide's checkpoints rather than treating these automated results as proof of every device configuration.

The installer's firmware build also completed in a fresh scratch application directory with its own PlatformIO installation and downloaded toolchain. It checked out the pinned source, initialized submodules, applied the SdFat 2.3.1 pin and produced the X4 Pro application image. This validates the build path; it does not mean that this separate smoke-test image was installed on a device.

Upstream was rechecked on 2026-09-29: the firmware source includes CrossPoint's current `develop` commit `d1509d0735bd0b7832c6765e2aa83e1f0c008eff`; the latest stable release at that check was 1.6.5. The custom firmware leaves the upstream Home activity and themes unchanged. Long-duration battery testing has not been performed.
