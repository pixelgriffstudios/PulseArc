# Portable media format

## Loose ROMs

A single ROM can be placed anywhere on USB, SD, CD, or DVD. PulseArc examines
both its extension and file signature. Multiple recognized games open the
multi-game browser. Subfolders are supported.

The first detector already distinguishes a PS1 `EBOOT.PBP` from a PSP PBP by
examining the PBP header and DATA.PSAR signature.

## Windows games

Windows games stay as ordinary folders. When a folder contains exactly one
usable executable, PulseArc can offer it automatically. A manifest is strongly
recommended when the game has launchers, setup programs, multiple EXEs, or
special compatibility requirements:

```text
My Game/
  pulsearc.toml
  cover.png
  Game.exe
  data/
```

The manifest is TOML, not a disk image or proprietary package. See
`examples/portable-windows-game/pulsearc.toml`.

For a keyboard-and-mouse-only PC game, an optional AntiMicroX profile may be
stored beside the game and referenced from `[input]`:

```toml
[input]
profile = "xbox"
antimicrox_profile = "controls/Game.gamecontroller.amgp"
```

The path must remain inside the game folder. PulseArc starts the profile only
for that title and stops AntiMicroX when the game exits. Games with native
controller support should omit this field.

## Legacy Kazeta `.kzi` cartridges

PulseArc recognizes a legacy `cart.kzi`, translates its metadata in memory,
and launches the payload with an equivalent internal runtime. The cartridge
remains read-only and bundled `.kzr` runtime images are not installed. Safe
legacy `Id` values are retained so migrated saves remain predictable.

An old PC cart may opt into per-game AntiMicroX mapping without changing its
launcher:

```ini
Name=Example Game
Id=example-game
Exec=content/Game.exe
Runtime=windows-1.0
Controller=controls/Game.gamecontroller.amgp
```

If no `Controller` line is present, existing controller behavior is unchanged.

## Optical media

Physical PS1, PS2, Sega CD, Saturn, PC Engine CD, Dreamcast backups, GameCube,
Wii, and data discs are resolved by filesystem and disc signatures. Optical
support will use direct streaming where the emulator supports a device or cue
sheet. An optional install action copies the image to internal storage with a
progress meter.

## Filesystems

The target image includes read support for exFAT, FAT32, NTFS, ext4, UDF, and
ISO9660. ext4 and Btrfs are recommended for Linux-owned writable storage;
exFAT is recommended for removable media shared with Windows.
