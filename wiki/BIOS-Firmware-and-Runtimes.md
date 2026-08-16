# BIOS, Firmware, and Runtimes

PulseArc's full image includes its emulators and Windows compatibility tools. It intentionally excludes copyrighted console firmware, decryption keys, title keys, commercial games, and private credentials.

## BIOS Manager

1. Obtain firmware legally from hardware or media you own.
2. Copy files to a USB or SD drive. Subfolders are allowed.
3. Insert the drive into PulseArc.
4. Open **Extras > BIOS Manager**.
5. Select a missing entry and choose import.
6. BIOS Manager scans the media, validates candidates, and places the selected file into PulseArc's private firmware directory.

Do not rename random files to match a BIOS filename. A wrong-size or wrong-region file can prevent a runtime from booting.

## Recognized firmware names

| System | Accepted file(s) |
|---|---|
| PlayStation | `scph5501.bin` |
| PlayStation 2 | `scph10000.bin` |
| Wii U | `keys.txt` |
| PlayStation 3 | `PS3UPDAT.PUP` |
| PS3 disc keys | `.key` or `.dkey` archive/files as supported |
| Dreamcast | `dc_boot.bin`, `dc_flash.bin` |
| Sega CD (USA) | `bios_CD_U.bin` |
| Saturn | `sega_101.bin` or `mpr-17933.bin` |
| PC Engine CD | `syscard3.pce` |
| Amiga | `kick34005.a500`, `kick40068.a1200`, `kick40068.a4000` |

Other regions or emulator versions can require different firmware. BIOS Manager is the authority for what the installed release currently recognizes.

## Included runtime families

The full image includes RetroArch cores and standalone emulators, including:

- Nintendo: Mesen, Nestopia, Snes9x, mGBA, melonDS, Mupen64Plus-Next, Dolphin, and Cemu.
- Sega: Genesis Plus GX, BlastEm, PicoDrive, Kronos, Beetle Saturn, and Flycast.
- Sony: Beetle PSX HW, DuckStation, PCSX2, PPSSPP, Vita3K, and RPCS3.
- Arcade/computers: FinalBurn Neo, MAME, DOSBox Pure/Staging, ScummVM, VICE, and PUAE.
- Atari: Stella, ProSystem, Handy, and Virtual Jaguar.
- Other standalone options include Azahar and xemu.
- Windows games use Wine-GE with DXVK, VKD3D-Proton, or WineD3D fallback.

PulseArc selects the runtime from the media signature and system. Users normally do not choose an emulator before every launch.

## Performance guidance

Start at native or modest internal resolution. Increase it only after gameplay is stable. Vulkan is preferred on capable hardware, while OpenGL/X11 fallback keeps the menu and older GPUs usable. A newer emulator is not automatically faster on an older CPU.
