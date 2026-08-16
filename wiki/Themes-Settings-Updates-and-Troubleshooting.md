# Themes, Settings, Updates, and Troubleshooting

## Themes and backgrounds

Open **Extras > Theme Management** to select an installed theme or import a theme ZIP from USB/SD. PulseArc scans common `PulseArc/Themes` and `Themes` folders. Older compatible theme assets can fall back to their background image when a dedicated preview is absent.

Settings controls background, screensaver, menu sounds, artwork downloads, start screen, audio, output resolution, and supported runtime options. Reset Settings restores PulseArc defaults; it does not erase installed games or firmware.

## Screensavers

Built-in choices include Off, Retro Grid, Neon Starfield, and Bouncing Pulse Orb. The default idle delay is 30 seconds. Controller or keyboard input dismisses the screensaver. Screensavers do not run over an active game or movie.

## Updates

Use **Extras > Check for Updates**. PulseArc uses transactional updates: it validates the package, rejects unsafe paths, stages the new files, and rolls back if application fails. Never interrupt power during staging or finalization.

Updates should preserve profiles, saves, user settings, imported BIOS files, installed games, themes, and credentials. A major release may require a documented migration, but users should not need to install every old update in sequence when the current update declares a supported upgrade path.

## Cover artwork

Enable artwork downloads in Settings. PulseArc queues lookups rather than blocking the menu, so a large USB drive can populate covers in batches. Local `cover.png` files are the reliable offline fallback. A wrong result can be replaced manually without renaming the game.

## Troubleshooting

### Play remains disabled

- Wait for the media scan to finish.
- Reinsert the drive after safely ejecting it.
- Confirm the filesystem and extension are supported.
- For a Windows folder, add a valid `pulsearc.toml`.
- Keep cue sheets and matching tracks together.

### A game immediately returns to the menu

- Check BIOS Manager for missing firmware.
- Verify the ROM/disc dump and region.
- Lower internal resolution.
- Change a Windows cart renderer from `auto` to `wined3d` only when Vulkan/DXVK fails.
- Remove a bad per-game controller or cheat override.

### No controller input

- Test it in Controllers before launching a game.
- Reconnect or re-pair it.
- Remove unnecessary AntiMicroX mapping from games with native controller support.
- Use View + A/South for the emulator menu and inspect the emulator port mapping.

### No HDMI audio

- Turn on the TV/receiver before booting.
- Select HDMI/DisplayPort in Settings and test volume.
- Reboot once after changing GPU, display, or profile.

### Optical disc is slow or unnamed

Scratched media can require repeated reads. Clean the disc and test another drive. A serial such as `SLUS-...` means the disc was identified but title metadata was unavailable. Installing an owned disc internally can avoid repeated optical reads.

### Update fails

Do not manually copy update files into system directories. Record the exact error, restart PulseArc, and retry Check for Updates. If rollback succeeded, the prior version remains active. Report the version, hardware, and error through the [issue tracker](https://github.com/pixelgriffstudios/PulseArc/issues).

## Reporting a reproducible bug

Include the PulseArc version, CPU/GPU, connection type, display resolution, controller model, media filesystem, game system, launch source (USB/internal/disc), and exact error. Do not post BIOS files, keys, passwords, account tokens, or copyrighted game data.
