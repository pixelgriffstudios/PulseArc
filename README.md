# PulseArc OS

PulseArc OS is a controller-first Linux gaming system built independently from
PlayFusion, Kazeta, Kazeta+, and Batocera. The name is a working project name
and can be changed before the first branded release.

The project launches games directly from internal storage, USB drives, SD
cards, CDs, and DVDs. It does not use KZI containers. A loose ROM normally
needs no metadata file. A portable Windows game can include one small
`pulsearc.toml` file when it needs an explicit executable or compatibility
settings.

## Design goals

- Newer Arch Linux base, pinned per release for repeatable builds.
- Internal emulators and Windows compatibility tools.
- Native OpenGL and Vulkan support.
- DirectX 8-11 through DXVK, DirectX 12 through VKD3D-Proton, and WineD3D as
  an OpenGL fallback.
- Controller-first interface with keyboard and mouse support where needed.
- Read-only removable media and profile-isolated saves.
- Direct loose-ROM, multi-ROM, optical-disc, and Windows-folder launching.
- Safe Xorg/OpenGL fallback for older Intel graphics; Gamescope is never a
  mandatory boot dependency.
- Transactional updates with rollback instead of in-place script mutation.
- User-supplied BIOS and keys; copyrighted firmware is never bundled.
- Xbox-style controller defaults with per-system and per-game overrides.
- Native boot animation before the controller menu.
- Profile-aware save backup/restore manager and opt-in cheat manager.
- Automatic cover metadata queue with offline caching and manual overrides.
- SSH/SFTP in development images for first-hardware diagnostics.
- FAT32, exFAT, NTFS, ext4, Btrfs, XFS, F2FS, ISO9660, and UDF media.

## Repository layout

- `src/pulsearc/` - media detection and launch-planning core.
- `tests/` - host-runnable unit tests.
- `archiso/` - ArchISO profile and root filesystem overlay.
- `config/` - emulator and Windows runner policy.
- `docs/` - architecture, media format, and development roadmap.
- `examples/` - portable game examples.
- `scripts/` - build and validation entry points.

## Host-side validation

The detector uses only Python's standard library:

```powershell
python -m unittest discover -s tests -v
```

## Building the operating-system ISO

The ISO must be built on an Arch Linux build host or VM with `archiso`
installed. Runtime bundles are downloaded only from the locked official URLs
in `config/runtime-lock.json` and must match their recorded SHA-256 values:

```bash
sudo pacman -Syu --needed archiso
sudo ./scripts/build-iso.sh
```

ArchISO's `mkarchiso` assembles the package list, root filesystem overlay,
kernel, initramfs, and bootable installer image. A public release is not made
until the ISO boots in a VM, installs to a blank virtual disk, boots that disk,
indexes test media, and launches at least one native emulator plus each Windows
renderer path available to the virtual hardware. Do not build a release ISO
against an unpinned rolling mirror; the release process uses a dated Arch Linux
Archive snapshot.

## Current milestone

The first public beta includes the frontend, direct-media scanner, runtime
registry, graphics fallback policy, offline SSD recovery installer, save and
cheat inventories, cover queue, and locked internal runtimes. It is intended
for testing on spare hardware. Back up important disks before installing and
report hardware-specific issues through the repository issue tracker.
