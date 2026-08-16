# Loose ROMs and Removable Media

## One ROM

Place a supported ROM anywhere on an exFAT, FAT32, NTFS, or Linux-formatted USB/SD drive. Insert the drive and wait for the scan. With one recognized game, **Play** launches it directly. PulseArc creates a stable internal content ID so saves continue to match even if the ROM is later renamed.

## Multiple ROMs

Subfolders are supported. When multiple games are found, Play opens the multi-game browser. Use LB/RB to page, A/South to play, and the on-screen install control to copy a selected title internally. **Install All** copies every supported title that is not already installed.

Files unrelated to supported games are hidden from the game browser. Music and movies can also be detected but appear in their appropriate media areas after installation.

## Common supported extensions

- Nintendo: `.nes`, `.fds`, `.sfc`, `.smc`, `.gb`, `.gbc`, `.gba`, `.nds`, `.3ds`, `.cci`, `.cxi`, `.z64`, `.n64`, `.v64`, `.gcm`, `.wbfs`, `.rvz`, `.wud`, `.wux`
- Sega: `.sms`, `.gg`, `.md`, `.gen`, `.32x`, `.gdi`, `.cdi`
- Sony/PSP/Vita: `.cue`, `.bin`, `.chd`, `.iso`, `.pbp`, `.cso`, `.vpk`
- NEC/Atari/computers: `.pce`, `.a26`, `.a78`, `.lnx`, `.j64`, `.jag`, `.d64`, `.t64`, `.prg`, `.adf`, `.adz`

PulseArc uses file signatures and disc contents as well as extensions. For example, it distinguishes a PlayStation `EBOOT.PBP` from a PSP PBP.

## Disc images and multi-file games

Keep cue sheets beside their matching BIN tracks and do not rename only one part. PulseArc resolves `.cue`, `.bin`, `.iso`, `.chd`, `.gdi`, and `.cdi` by content. Avoid selecting individual audio/data tracks as separate games.

## Physical optical media

PulseArc can identify supported PS1, PS2, Sega CD, Saturn, PC Engine CD, Dreamcast backup, GameCube, Wii, and data discs. It streams directly when the emulator supports the device. PS1/PS2 titles can also be installed internally with a progress display. If online metadata is unavailable, a physical game may initially display its disc serial instead of its title.

Commercial movie DVDs use the media player rather than a console runtime. PulseArc does not provide tools to bypass copy protection.

## Music and movie files

Common music formats include `.mp3`, `.wav`, `.flac`, `.ogg`, `.opus`, `.m4a`, and `.aac`. Common video formats include `.mp4`, `.mkv`, `.avi`, `.mov`, `.m4v`, `.webm`, `.mpg`, `.mpeg`, `.ts`, and `.m2ts`.

For clean organization, store movies under `Movies/`, TV episodes under a show-specific folder inside `Shows/` or `TV Shows/`, and music under `Music/Artist/Album/`. Artwork is cached when downloads are enabled; a local `cover.png` remains the most reliable offline override.

## Safely removing media

Do not unplug media while its light is active or while PulseArc shows copying, installing, finalizing, recording, or saving. Return to the main screen, wait for activity to stop, and use the operating system's eject option when available.
