# Development roadmap

## Milestone 0 - foundation (current)

- Independent source tree and working name.
- ArchISO skeleton and internal package plan.
- Direct extension/signature media detector.
- PS1 versus PSP PBP identification.
- Safe portable Windows-game manifest.
- Stable content IDs and unit tests.

## Milestone 1 - bootable developer image

- Complete ArchISO profile and pinned package mirror.
- Boot to a basic controller-driven PulseArc session.
- udev/udisks removable-media discovery.
- Launch NES, SNES, Genesis, N64, PS1, PSP, and one portable Windows game.
- Per-profile saves and a reliable exit hotkey.

## Milestone 2 - emulator suite

- Internal standalone emulators and RetroArch cores.
- BIOS manager with hashes and missing-file guidance.
- Per-system controller templates and hotkeys.
- GameCube/Wii, PS2, Dreamcast, DS/3DS, Wii U, Xbox, DOS, ScummVM, arcade,
  Amiga, C64, Atari, and PC Engine validation.

## Milestone 3 - installer and transactions

- Controller-friendly disk installer.
- UEFI and legacy BIOS testing.
- Btrfs snapshot updates, boot health checks, and rollback.
- Multi-drive game storage.

## Milestone 4 - polished public release

- Console-first UI with the proven PlayFusion information architecture: main
  menu, media browser, internal library, saves, cheats, settings, extras,
  profile status and power controls.
- New PulseArc visual identity and theme format; no PlayFusion/Kazeta artwork
  dependency.
- Artwork/metadata cache.
- Movies and jukebox as optional modules.
- Hardware compatibility matrix and automated VM/real-hardware smoke tests.
