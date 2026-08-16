# Getting Started

## Download and reassemble the installer

Download every numbered image part, the SHA-256 file, and the reassembly script for your operating system from the [PulseArc beta release](https://github.com/pixelgriffstudios/PulseArc/releases/tag/v0.1.0-beta.1). Keep them together in one folder.

### Windows

Open PowerShell in that folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\Reassemble-PulseArc.ps1
```

### Linux

```bash
chmod +x reassemble-pulsearc.sh
./reassemble-pulsearc.sh
```

The supplied scripts join the parts and verify the finished image against its published SHA-256. Do not flash an image that fails verification.

## Flash and install

1. Flash the reconstructed `.img` to a USB drive with balenaEtcher or another raw-image writer.
2. Back up every important file on the destination PC.
3. Boot the USB drive in UEFI mode. Disable Secure Boot if the computer refuses to boot the unsigned development image.
4. Choose the internal destination carefully. The selected destination is erased.
5. Let verification and restoration finish without disconnecting power or either drive.
6. Shut down, remove the installer USB, and boot the internal drive.

The destination can be larger than the source image. PulseArc expands its data storage to use the available space during installation/first boot.

## First boot checklist

1. Confirm the main menu appears at the TV's native resolution.
2. Open **Settings > Audio** and select HDMI/DisplayPort audio when needed.
3. Set master volume and test menu sounds.
4. Open **Controllers** and verify the D-pad, sticks, A/B buttons, shoulders, and View/Menu buttons.
5. Open **Extras > Wi-Fi** if Ethernet is unavailable.
6. Open **Extras > BIOS Manager** and import only firmware you legally obtained.
7. Insert a test ROM or portable Windows game on USB/SD and confirm **Play** becomes available.
8. Install a test game to the Library, launch it, exit it, and confirm its save is present.

## Storage formats

- **exFAT** is recommended for USB and SD media shared with Windows and Linux.
- **FAT32** works but cannot store an individual file larger than 4 GB.
- **NTFS** is supported for shared media.
- **ext4** and **Btrfs** are recommended for Linux-owned writable internal storage.
- Optical media uses ISO9660/UDF where appropriate.

Never format a drive simply because Windows says a Linux partition is unreadable. Windows normally cannot browse ext4 without additional software.
