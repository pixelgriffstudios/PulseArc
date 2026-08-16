# Windows Game Carts

PulseArc does not require a proprietary cartridge image for Windows games. A “cart” is an ordinary portable game folder on USB, SD, optical data media, or another supported drive. This makes it readable on Windows and Linux and avoids embedding a runtime on every cart.

## Recommended folder structure

```text
My Game/
  pulsearc.toml
  cover.png
  Game.exe
  data/
  controls/
    Game.gamecontroller.amgp
```

`cover.png` and the `controls` folder are optional. Keep every referenced path inside the game folder.

## Manifest example

```toml
[game]
title = "My Game"
platform = "windows"
entrypoint = "Game.exe"
working_directory = "."
arguments = ["-fullscreen"]
runner = "wine-ge"
renderer = "auto"

[display]
internal_width = 1280
internal_height = 720
output = "auto"
integer_scale = false

[input]
profile = "xbox"
keyboard_overlay = true
# antimicrox_profile = "controls/Game.gamecontroller.amgp"
```

The required game fields are `title`, `platform`, and `entrypoint`. `working_directory` and all referenced files must stay inside the cart folder.

## Renderer choices

- `auto` selects the best available path and is recommended.
- `vulkan` requires DXVK/VKD3D-Proton and suitable Vulkan hardware.
- `opengl` or `wined3d` uses Wine's OpenGL translation for older hardware or incompatible games.

PulseArc includes Wine-GE and chooses modern or legacy compatibility paths based on the detected GPU. Do not copy system Wine files into each game folder.

## AntiMicroX mapping

Games with native controller support should omit `antimicrox_profile`. For a keyboard-and-mouse-only game:

1. Open **Extras > AntiMicroX Profiles**.
2. Create and test a per-game Xbox-style mapping.
3. Save the `.amgp` or `.xml` file inside the game's `controls` folder.
4. Add the relative `antimicrox_profile` path under `[input]`.

PulseArc starts that profile only while the game is running and stops it when the game exits.

## Preparing the drive

1. Format the removable drive as exFAT for broad compatibility.
2. Copy the complete game folder to the root or any subfolder.
3. Safely eject it from the source computer.
4. Insert it into PulseArc and wait for scanning to finish.
5. Choose **Play**, or use the install action to copy it to the internal Library.

A folder containing exactly one usable EXE may be detected automatically, but a manifest is strongly recommended whenever there are launchers, setup tools, multiple executables, command-line arguments, or special renderer settings.

## Important limitations

- The folder must contain an already portable or correctly installed game with all redistributable files it legally requires.
- DRM launchers may require Steam or Heroic from the Apps screen and an online account.
- An installer EXE is not automatically equivalent to a portable game cart.
- Test the game on the target hardware before archiving or duplicating the cart.

## Legacy Kazeta KZI carts

PulseArc can read legacy `cart.kzi` metadata and translate it in memory. The media remains read-only and bundled `.kzr` runtime images are ignored because PulseArc uses its internal runtimes. Existing safe IDs are retained for predictable saves.

A legacy PC cart may reference a bundled AntiMicroX profile:

```ini
Name=Example Game
Id=example-game
Exec=content/Game.exe
Runtime=windows-1.0
Controller=controls/Game.gamecontroller.amgp
```
