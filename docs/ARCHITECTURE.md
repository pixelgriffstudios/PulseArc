# Architecture

## Base operating system

PulseArc uses Arch Linux and ArchISO, but each public release is built from a
dated package snapshot. A release never silently changes because the normal
Arch mirrors moved forward.

The installed system uses:

- GRUB on UEFI and legacy BIOS systems, including a removable-media UEFI path;
- Btrfs root, home, state, and snapshot subvolumes;
- a layout reserved for future read-only release snapshots;
- a future transactional update path that must be implemented and tested
  before network updates are enabled.

## Runtime layers

1. **Native Linux:** Vulkan or OpenGL applications run directly.
2. **Retro emulation:** RetroArch cores are used where they are mature and
   standalone emulators are used when their compatibility is better.
3. **Windows:** Wine-GE/Proton-GE is isolated per game. DXVK provides D3D8-11
   over Vulkan, VKD3D-Proton provides D3D12 over Vulkan, and WineD3D provides
   an OpenGL fallback.
4. **Display:** Gamescope gives capable systems a private display and
   predictable scaling. It is optional. Systems that fail a startup probe use
   direct Xorg/OpenGL, so an unsupported Vulkan compositor cannot black-screen
   the entire machine.

All runtimes ship internally. Runtime downloads are updates, not prerequisites
for normal use. BIOS, firmware, encryption keys, and commercial game content
remain user supplied.

## Services

- `pulsearc-media`: mounts supported removable media read-only, indexes it,
  creates stable content IDs, and publishes the library atomically.
- `pulsearc-metadata`: resolves and caches optional cover art without blocking
  scanning or launching.
- `pulsearc-session`: owns the controller-first frontend session.
- `pulsearc.control`: applies the selected runtime, renderer, Gamescope,
  controller, and profile save root, then records a per-launch log.

The update service is intentionally absent from this pre-alpha. It will not be
enabled until snapshot rollback and failed-boot recovery pass destructive VM
tests.

## Storage and saves

Removable media is mounted read-only by default. Save data is never written
beside a ROM. It lives under:

```text
/var/lib/pulsearc/profiles/<profile-id>/saves/<content-id>/
```

`content-id` is based on content samples and size, so renaming the ROM does not
lose its save. Full cryptographic hashes can be computed in the background for
metadata matching.

## Frontend

The frontend is Godot 4 using the compatibility renderer for the menu.
That keeps animated themes and controller navigation easy while allowing the
menu itself to run on older OpenGL hardware. Individual games and emulators can
still use Vulkan.

## Older Intel graphics

Third-generation Intel HD 4000 (Ivy Bridge) must be treated as an OpenGL-first
target. Fourth-generation Haswell is tested for Vulkan at startup but is not
assumed to support the current Gamescope/DXVK stack. PulseArc therefore boots
its menu through Xorg/OpenGL first, runs a separate Gamescope health test, and
only enables Gamescope when that test succeeds.

Windows games have three paths: modern DXVK on Vulkan 1.4, legacy DXVK 1.10.3
on suitable Vulkan 1.1 hardware, and WineD3D on OpenGL. D3D12 is not promised
on the older Intel path.

## Release qualification

A version number does not make a build a release. Before publishing, the same
ISO must pass these gates:

1. Package-name and runtime-hash validation.
2. Host-side unit, Godot parse, and shell syntax tests.
3. UEFI VM boot into the live frontend.
4. Destructive install into a blank, differently sized virtual disk.
5. Installed-disk reboot with the installer media detached.
6. FAT32, exFAT, ext4, and ISO/UDF read-only media detection.
7. Save isolation across profiles and backup/restore validation.
8. OpenGL fallback and Vulkan launch-path smoke tests.
9. At least one real-hardware pass before any public GitHub release.

## Recovery disk image

The primary hardware deployment artifact is a preinstalled raw GPT disk image,
not an installer that reconstructs the operating system on the destination PC.
The image already contains the kernel, bootloader, EFI fallback path, and root
filesystem. It is written directly to the destination SSD with an image writer.
On first boot, `pulsearc-expand-root.service` moves the backup GPT header and
expands the Btrfs root partition to the physical disk's full capacity.
