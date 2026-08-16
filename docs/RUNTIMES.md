# Internal runtime policy

PulseArc treats emulators and compatibility tools as operating-system
components. A user inserts a loose game; the scanner identifies the system and
the runtime registry chooses a primary emulator and an installed fallback.
There are no KZI runtime payloads.

The full image contains RetroArch cores and standalone emulators for the major
Nintendo, Sega, Sony, Atari, Commodore, DOS, arcade, and Windows families.
Signed Arch repository packages are preferred. Projects absent from the signed
repositories are repackaged only from their official upstream release, pinned
by version and SHA-256. The AUR is not a release-build dependency.

Console firmware, decryption keys, and title keys are never part of the public
image or source repository. The BIOS manager imports user-supplied files into
`/var/lib/pulsearc/firmware` and reports missing/valid/invalid state.

Windows games use Wine-GE plus one of three hardware-selected paths:

- Vulkan 1.4 plus required features: current DXVK and VKD3D-Proton, optionally nested in Gamescope.
- Vulkan 1.1 through 1.3: DXVK 1.10.3 on X11.
- No usable Vulkan: WineD3D over OpenGL on X11.

The frontend is PulseArc's native Python/Pygame UI and does not use Godot.
Gamescope or Vulkan failures therefore do not prevent the menu from starting.

## PC stores and cloud apps

The Apps screen includes these controller-oriented launchers:

- **Steam Big Picture** uses the native Linux Steam client. Sign in once to
  view the account's owned library, install games, and run them. Account data,
  controller layouts, Proton prefixes, and the default game library persist
  under the `gamer` home directory. Additional mounted drives can be added
  through Steam's Storage settings.
- **Epic + GOG Library (Heroic)** uses the bundled, checksum-locked Heroic
  AppImage. Epic and GOG accounts and installed games persist. The default
  install folder is `~/Games/Heroic`.
- **Xbox Game Pass Cloud Gaming** and **GeForce NOW** open in a dedicated
  Firefox kiosk profile with controller navigation. These services require
  their normal accounts and subscriptions. GeForce NOW prefers its native
  Linux client when installed and falls back to its web client.
- **PlayStation Plus Cloud Gaming** uses the isolated Wine-GE launcher
  described below.

The full operating-system image includes Steam, Firefox, Flatpak, and Heroic;
these menu entries are not placeholders.

## PlayStation Plus cloud gaming

The Apps screen launches Sony's PlayStation Plus PC cloud-streaming client
through PulseArc's isolated Wine-GE prefix. This integration is for PlayStation
Plus cloud gaming only; it does not install or use PS Remote Play, PXPlay, or
Chiaki. The first launch downloads the official Sony client and Microsoft's
required Visual C++ component over HTTPS, validates both as bounded PE files,
and installs them as the unprivileged `gamer` user. Account sign-in remains in
Sony's client and credentials are not stored by PulseArc.

An adult PlayStation account, a PlayStation Plus Premium subscription, a
compatible controller, and broadband Internet are required. Because Sony lists
Windows as the supported PC platform, Wine-GE compatibility can change when
Sony updates the client.

## RetroArch core matrix

The image carries the complete core coverage previously used by PlayFusion,
plus newer alternatives where they improve compatibility:

- Nintendo: Mesen, Nestopia, Snes9x, mGBA, melonDS and Mupen64Plus-Next.
- Sega: Genesis Plus GX, BlastEm, PicoDrive, Kronos, Beetle Saturn and Flycast.
- Sony: Beetle PSX HW and Beetle PCE for the related NEC platform.
- Arcade and computers: FinalBurn Neo, MAME, DOSBox Pure, VICE x64sc and PUAE.
- Atari: Stella, ProSystem, Handy and Virtual Jaguar.

Standalone DuckStation, PCSX2, PPSSPP, Dolphin, Cemu, Azahar, Vita3K, xemu,
RPCS3, MAME, ScummVM, DOSBox Staging and VICE remain available where a
standalone emulator is the better choice.

`scripts/validate-runtime-matrix.py` checks every configured RetroArch runner
against either a signed Arch package or a checksum-pinned bundled core. The ISO
build stops if a system references an unknown runner, if a core has no package
source, if a bundled target path differs from the registry, or if an extracted
core is absent.
