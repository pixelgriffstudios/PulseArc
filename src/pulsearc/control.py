from __future__ import annotations

import argparse
import configparser
import ctypes
import ctypes.util
import html
import json
import os
import re
import signal
import stat
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

from .graphics import GraphicsPolicy
from .launch import create_launch_plan
from .registry import RuntimeRegistry
from .cheats import Cheat, cheat_file, load_cheats, save_cheats, set_cheat_enabled
from .cheat_export import export_duckstation, export_retroarch
from .rpcs3_patches import discover_patches, export_patch_config
from .controllers import validate_antimicrox_profile
from .saves import inventory


INDEX = Path("/run/pulsearc/library.json")
SYSTEM_REGISTRY = Path("/usr/share/pulsearc/config/systems.toml")
USER_REGISTRY = Path.home() / ".config/pulsearc/systems.toml"
REGISTRY = USER_REGISTRY if USER_REGISTRY.is_file() else SYSTEM_REGISTRY
STATE = Path("/var/lib/pulsearc")

RETROARCH_DEFAULTS = {
    "video_fullscreen": "true", "video_windowed_fullscreen": "true",
    "input_driver": "x", "input_joypad_driver": "udev", "input_autodetect_enable": "true",
    "input_player1_joypad_index": "0", "input_player1_a_btn": "1", "input_player1_b_btn": "0",
    "input_player1_x_btn": "3", "input_player1_y_btn": "2", "input_player1_l_btn": "4",
    "input_player1_r_btn": "5", "input_player1_select_btn": "6", "input_player1_start_btn": "7",
    "input_player1_l3_btn": "9", "input_player1_r3_btn": "10",
    # Linux exposes Xbox 360/One triggers as positive analog axes. Mupen64Plus
    # maps RetroPad L2 to the N64 Z trigger and R2 to C-button mode.
    "input_player1_l2_axis": "+2", "input_player1_r2_axis": "+5",
    "input_player1_up_btn": "h0up", "input_player1_down_btn": "h0down",
    "input_player1_left_btn": "h0left", "input_player1_right_btn": "h0right",
    "input_player1_l_x_minus_axis": "-0", "input_player1_l_x_plus_axis": "+0",
    "input_player1_l_y_minus_axis": "-1", "input_player1_l_y_plus_axis": "+1",
    "input_player1_r_x_minus_axis": "-3", "input_player1_r_x_plus_axis": "+3",
    "input_player1_r_y_minus_axis": "-4", "input_player1_r_y_plus_axis": "+4",
    # Select is the modifier: Select+Start exits and Select+physical A opens
    # RetroArch's Quick Menu on every core.
    "input_enable_hotkey_btn": "6", "input_exit_emulator_btn": "7",
    "input_menu_toggle_btn": "0",
}

RETROARCH_CORE_NAMES = {
    "retroarch-mesen": "Mesen",
    "retroarch-nestopia": "Nestopia",
    "retroarch-snes9x": "Snes9x",
    "retroarch-mgba": "mGBA",
    "retroarch-mupen64plus-next": "Mupen64Plus-Next",
    "retroarch-genesis-plus-gx": "Genesis Plus GX",
    "retroarch-flycast": "Flycast",
}

DUCKSTATION_DEFAULTS = {
    "Main": {
        "ApplyGameSettings": "true",
        "ConfirmPowerOff": "false",
        "HideCursorInFullscreen": "true",
        "HideMainWindowWhenRunning": "true",
        # Prevent DuckStation from offering to create a desktop/menu shortcut
        # for every newly discovered or internally installed PS1 title.
        "NoDesktopFile": "true",
        "PauseOnControllerDisconnection": "false",
        "PauseOnFocusLoss": "false",
        "SaveStateOnExit": "true",
        "SetupWizardIncomplete": "false",
        "StartFullscreen": "true",
    },
    "AutoUpdater": {"CheckAtStartup": "false"},
    "GPU": {"Renderer": "Vulkan", "ResolutionScale": "4"},
    "InputSources": {"SDL": "true", "XInput": "false"},
    "Pad1": {
        "Type": "AnalogController",
        "Up": "SDL-0/DPadUp", "Down": "SDL-0/DPadDown",
        "Left": "SDL-0/DPadLeft", "Right": "SDL-0/DPadRight",
        "Cross": "SDL-0/A", "Circle": "SDL-0/B",
        "Square": "SDL-0/X", "Triangle": "SDL-0/Y",
        "L1": "SDL-0/LeftShoulder", "R1": "SDL-0/RightShoulder",
        "L2": "SDL-0/+LeftTrigger", "R2": "SDL-0/+RightTrigger",
        "L3": "SDL-0/LeftStick", "R3": "SDL-0/RightStick",
        "Select": "SDL-0/Back", "Start": "SDL-0/Start",
        "LLeft": "SDL-0/-LeftX", "LRight": "SDL-0/+LeftX",
        "LUp": "SDL-0/-LeftY", "LDown": "SDL-0/+LeftY",
        "RLeft": "SDL-0/-RightX", "RRight": "SDL-0/+RightX",
        "RUp": "SDL-0/-RightY", "RDown": "SDL-0/+RightY",
    },
    "Hotkeys": {
        "OpenPauseMenu": "SDL-0/Back & SDL-0/A",
        "PowerOff": "SDL-0/Back & SDL-0/Start",
    },
}

PCSX2_DEFAULTS = {
    "UI": {
        "SetupWizardIncomplete": "false",
        "StartFullscreen": "true",
        "HideMouseCursor": "true",
        "HideMainWindowWhenRunning": "true",
        "PauseOnFocusLoss": "false",
        "ConfirmShutdown": "false",
    },
    "Folders": {"Bios": "bios"},
    "Filenames": {"BIOS": "scph10000.bin"},
    "InputSources": {
        "Keyboard": "true",
        "Mouse": "false",
        "SDL": "true",
        "SDLControllerEnhancedMode": "false",
    },
    "Pad1": {
        "Type": "DualShock2",
        "Up": "SDL-0/DPadUp", "Down": "SDL-0/DPadDown",
        "Left": "SDL-0/DPadLeft", "Right": "SDL-0/DPadRight",
        "Cross": "SDL-0/A", "Circle": "SDL-0/B",
        "Square": "SDL-0/X", "Triangle": "SDL-0/Y",
        "L1": "SDL-0/LeftShoulder", "R1": "SDL-0/RightShoulder",
        "L2": "SDL-0/+LeftTrigger", "R2": "SDL-0/+RightTrigger",
        "L3": "SDL-0/LeftStick", "R3": "SDL-0/RightStick",
        "Select": "SDL-0/Back", "Start": "SDL-0/Start",
        "LLeft": "SDL-0/-LeftX", "LRight": "SDL-0/+LeftX",
        "LUp": "SDL-0/-LeftY", "LDown": "SDL-0/+LeftY",
        "RLeft": "SDL-0/-RightX", "RRight": "SDL-0/+RightX",
        "RUp": "SDL-0/-RightY", "RDown": "SDL-0/+RightY",
        "Analog": "SDL-0/Guide",
        "LargeMotor": "SDL-0/LargeMotor", "SmallMotor": "SDL-0/SmallMotor",
    },
    "Pad2": {"Type": "None"},
    "EmuCore/GS": {
        # Automatic selects Vulkan on the Vega 8 while retaining a safe
        # fallback for older GPUs supported by PulseArc.
        "Renderer": "-1",
        "upscale_multiplier": "3",
        "AspectRatio": "Auto 4:3/3:2",
    },
}


def _prepare_duckstation_config(save_root: Path) -> Path:
    """Seed console-safe DuckStation settings while preserving saves/settings."""
    config = save_root / "config/duckstation/settings.ini"
    config.parent.mkdir(parents=True, exist_ok=True)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    if config.is_file():
        parser.read(config, encoding="utf-8")
    for section, values in DUCKSTATION_DEFAULTS.items():
        if not parser.has_section(section):
            parser.add_section(section)
        for key, value in values.items():
            parser.set(section, key, value)
    temporary = config.with_suffix(".ini.tmp")
    with temporary.open("w", encoding="utf-8") as output:
        parser.write(output, space_around_delimiters=True)
    # DuckStation stores multiple bindings for one hotkey as repeated INI
    # keys. Keep Escape alongside the controller chord. ConfigParser cannot
    # represent repeated keys directly, so add the second binding after its
    # otherwise atomic serialization.
    serialized = temporary.read_text(encoding="utf-8")
    controller_binding = "OpenPauseMenu = SDL-0/Back & SDL-0/A\n"
    if controller_binding in serialized:
        serialized = serialized.replace(
            controller_binding,
            controller_binding + "OpenPauseMenu = Keyboard/Escape\n",
            1,
        )
        temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(config)
    return config


def _prepare_pcsx2_config(save_root: Path) -> Path:
    """Finish PCSX2 setup and seed an Xbox-style SDL configuration."""
    config = save_root / "config/PCSX2/inis/PCSX2.ini"
    config.parent.mkdir(parents=True, exist_ok=True)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    if config.is_file():
        parser.read(config, encoding="utf-8")
    for section, values in PCSX2_DEFAULTS.items():
        if not parser.has_section(section):
            parser.add_section(section)
        for key, value in values.items():
            parser.set(section, key, value)
    temporary = config.with_suffix(".ini.tmp")
    with temporary.open("w", encoding="utf-8") as output:
        parser.write(output, space_around_delimiters=True)
    temporary.replace(config)
    return config


def _first_linux_gamepad_name() -> str:
    """Return the first joystick name in the same form RPCS3's SDL handler uses."""
    # RPCS3 and pygame both obtain controller names from SDL.  Prefer pygame's
    # SDL name over the lower-level Linux evdev name, which differs for common
    # pads (for example "Xbox 360 Controller" vs "Microsoft X-Box 360 pad").
    try:
        import pygame

        pygame.joystick.init()
        if pygame.joystick.get_count():
            joystick = pygame.joystick.Joystick(0)
            joystick.init()
            name = joystick.get_name().strip()
            pygame.joystick.quit()
            if name:
                return name
        pygame.joystick.quit()
    except Exception:
        # The fallback keeps launch functional on minimal/headless systems.
        pass
    devices = Path("/proc/bus/input/devices")
    if not devices.is_file():
        return ""
    for block in devices.read_text(encoding="utf-8", errors="replace").split("\n\n"):
        if not any(token.startswith("js") for line in block.splitlines() if line.startswith("H: Handlers=")
                   for token in line.partition("=")[2].split()):
            continue
        for line in block.splitlines():
            if line.startswith("N: Name="):
                return line.partition("=")[2].strip().strip('"')
    return ""


def _prepare_rpcs3_config(
    save_root: Path,
    cheats: list[Cheat] | None = None,
    serial: str = "",
) -> Path:
    """Seed a console-safe 720p Vulkan profile and Xbox-style SDL controls."""
    root = save_root / "config/rpcs3"
    root.mkdir(parents=True, exist_ok=True)
    config = root / "config.yml"
    if not config.is_file():
        temporary = config.with_suffix(".yml.tmp")
        temporary.write_text(
            "Video:\n"
            "  Renderer: Vulkan\n"
            "  Resolution: 1280x720\n"
            "  Aspect ratio: 16:9\n"
            "  Resolution Scale: 100\n"
            "  Frame limit: Auto\n"
            "  VSync Mode: Disabled\n"
            "  Shader Mode: Async Recompiler with Shader Interpreter\n"
            "Audio:\n"
            "  Renderer: Cubeb\n"
            "  Audio Device: '@@@default@@@'\n"
            "  Master Volume: 100\n"
            "Input/Output:\n"
            "  Load SDL GameController Mappings: true\n"
            "  Background input enabled: true\n"
            "Miscellaneous:\n"
            "  Automatically start games after boot: true\n"
            "  Exit RPCS3 when process finishes: true\n"
            "  Start games in fullscreen mode: true\n"
            "  Prevent display sleep while running games: true\n",
            encoding="utf-8",
        )
        temporary.replace(config)
    else:
        # Repair names accepted by older RPCS3 builds.  Current releases log
        # them as invalid and silently substitute defaults.
        text = config.read_text(encoding="utf-8", errors="replace")
        repaired = text.replace("  VSync Mode: Off\n", "  VSync Mode: Disabled\n")
        repaired = repaired.replace(
            "  Shader Mode: Async Shader Recompiler\n",
            "  Shader Mode: Async Recompiler with Shader Interpreter\n",
        )
        if repaired != text:
            config.write_text(repaired, encoding="utf-8")

    if serial.replace("-", "").upper() in {"BCUS98174", "BLUS30443"}:
        # The Last of Us and Demon's Souls render important color targets
        # through memory.  Without WCB, RPCS3 can run normally while the 3D
        # scene is black (Demon's Souls may still show its HUD).
        text = config.read_text(encoding="utf-8", errors="replace")
        if "  Write Color Buffers:" in text:
            text = re.sub(
                r"(?m)^  Write Color Buffers:.*$",
                "  Write Color Buffers: true",
                text,
            )
        else:
            marker = "Video:\n"
            text = text.replace(marker, marker + "  Write Color Buffers: true\n", 1)
        config.write_text(text, encoding="utf-8")

    gamepad = _first_linux_gamepad_name()
    # RPCS3 stores named global profiles below input_configs/global.  Keeping
    # this file one level higher makes --input-config=PulseArc silently miss
    # it and fall back to the keyboard handler.
    input_config = root / "input_configs/global/PulseArc.yml"
    input_config.parent.mkdir(parents=True, exist_ok=True)
    legacy_input_config = root / "input_configs/PulseArc.yml"
    if legacy_input_config.is_file() and not input_config.exists():
        legacy_input_config.replace(input_config)
    device = gamepad + " 1" if gamepad else "SDL-1"
    if input_config.is_file():
        # Preserve the user's mappings while repairing only the handler/device
        # lines needed when a controller is changed or reconnected.
        lines = input_config.read_text(encoding="utf-8", errors="replace").splitlines()
        in_player_one = False
        saw_handler = False
        saw_device = False
        rewritten: list[str] = []
        for line in lines:
            if line and not line.startswith((" ", "\t")):
                in_player_one = line.rstrip() == "Player 1 Input:"
            if in_player_one and line.lstrip().startswith("Handler:"):
                rewritten.append("  Handler: SDL")
                saw_handler = True
            elif in_player_one and line.lstrip().startswith("Device:"):
                rewritten.append(f"  Device: {device}")
                saw_device = True
            else:
                rewritten.append(line)
        if not saw_handler or not saw_device:
            rewritten.extend([
                "Player 1 Input:" if "Player 1 Input:" not in lines else "",
                "  Handler: SDL" if not saw_handler else "",
                f"  Device: {device}" if not saw_device else "",
            ])
        input_config.write_text("\n".join(line for line in rewritten if line) + "\n", encoding="utf-8")
    else:
        input_config.write_text(
            "Player 1 Input:\n"
            "  Handler: SDL\n"
            f"  Device: {device}\n",
            encoding="utf-8",
        )

    shared = Path.home() / ".local/share/pulsearc/rpcs3-shared/rpcs3"
    for name in ("dev_flash", "dev_flash2", "dev_flash3"):
        source = shared / name
        destination = root / name
        if not source.exists():
            continue
        if destination.is_symlink() or destination.exists():
            if destination.is_symlink() and destination.resolve() == source.resolve():
                continue
            if destination.is_dir() and not destination.is_symlink():
                continue
            destination.unlink()
        destination.symlink_to(source, target_is_directory=True)
    key_source = STATE / "firmware/ps3/keys"
    if not key_source.is_dir():
        key_source = Path.home() / ".local/share/pulsearc/rpcs3-keys"
    key_destination = root / "data/redump"
    if key_source.is_dir() and not key_destination.exists():
        key_destination.parent.mkdir(parents=True, exist_ok=True)
        key_destination.symlink_to(key_source, target_is_directory=True)
    patch_source = Path.home() / ".local/share/pulsearc/rpcs3-patches/patch.yml"
    patch_destination = root / "patches/patch.yml"
    if patch_source.is_file() and not patch_destination.exists():
        patch_destination.parent.mkdir(parents=True, exist_ok=True)
        patch_destination.symlink_to(patch_source)
    export_patch_config(list(cheats or []), root / "patch_config.yml")
    return config


def _sync_rpcs3_cheats(entry: dict, profile_id: str) -> None:
    if str(entry.get("platform", "")) != "playstation-3":
        return
    serial = str(entry.get("serial", "")).replace("-", "").upper()
    if not serial:
        return
    database = Path.home() / ".local/share/pulsearc/rpcs3-patches/patch.yml"
    discovered = discover_patches(database, serial)
    if not discovered:
        return
    path = cheat_file(STATE, profile_id, "playstation-3", str(entry["content_id"]))
    existing = {item.cheat_id: item for item in load_cheats(path)} if path.is_file() else {}
    merged = [
        Cheat(item.cheat_id, item.name, item.code, existing.get(item.cheat_id, item).enabled)
        for item in discovered
    ]
    save_cheats(path, merged)


def _prepare_retroarch_config(
    save_root: Path,
    runner_id: str = "",
    content: Path | None = None,
    cheats: list | None = None,
) -> None:
    config = save_root / "config/retroarch/retroarch.cfg"
    config.parent.mkdir(parents=True, exist_ok=True)
    lines = config.read_text(encoding="utf-8", errors="replace").splitlines() if config.exists() else []
    rewritten: list[str] = []
    remaining = dict(RETROARCH_DEFAULTS)
    if content is not None and runner_id in RETROARCH_CORE_NAMES:
        cheat_root = save_root / "config/retroarch/cheats"
        remaining.update({
            "cheat_database_path": str(cheat_root),
            "apply_cheats_after_load": "true",
        })
        destination = cheat_root / RETROARCH_CORE_NAMES[runner_id] / f"{content.stem}.cht"
        export_retroarch(list(cheats or []), destination)
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in remaining:
            rewritten.append(f'{key} = "{remaining.pop(key)}"')
        else:
            rewritten.append(line)
    rewritten.extend(f'{key} = "{value}"' for key, value in remaining.items())
    temporary = config.with_suffix(".cfg.tmp")
    temporary.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    temporary.replace(config)
    if runner_id == "retroarch-beetle-psx-hw":
        options = save_root / "config/retroarch/retroarch-core-options.cfg"
        option_lines = options.read_text(encoding="utf-8", errors="replace").splitlines() if options.exists() else []
        option_lines = [line for line in option_lines if not line.strip().startswith("beetle_psx_hw_internal_resolution")]
        option_lines.append('beetle_psx_hw_internal_resolution = "4x"')
        option_temporary = options.with_suffix(".cfg.tmp")
        option_temporary.write_text("\n".join(option_lines) + "\n", encoding="utf-8")
        option_temporary.replace(options)


def _prepare_firmware(system_id: str, save_root: Path, state_root: Path = STATE) -> None:
    """Link user-imported firmware into an isolated per-game environment."""
    firmware = state_root / "firmware"
    links: list[tuple[Path, Path]] = []
    if system_id == "playstation":
        source = firmware / "ps1/scph5501.bin"
        links.extend((
            (source, save_root / "data/duckstation/bios/scph5501.bin"),
            (source, save_root / "config/duckstation/bios/scph5501.bin"),
            (source, save_root / "config/retroarch/system/scph5501.bin"),
        ))
    elif system_id == "playstation-2":
        source = firmware / "ps2/scph10000.bin"
        links.extend((
            (source, save_root / "config/PCSX2/bios/scph10000.bin"),
            (source, save_root / "data/PCSX2/bios/scph10000.bin"),
        ))
    elif system_id == "wii-u":
        source = firmware / "wiiu/keys.txt"
        links.extend((
            (source, save_root / "data/Cemu/keys.txt"),
            (source, save_root / "config/Cemu/keys.txt"),
            (source, save_root / "data/cemu/keys.txt"),
            (source, save_root / "config/cemu/keys.txt"),
        ))
    elif system_id == "dreamcast":
        for name in ("dc_boot.bin", "dc_flash.bin"):
            source = firmware / "dreamcast" / name
            links.append((source, save_root / "config/retroarch/system" / name))
    elif system_id == "sega-cd":
        for name in ("bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin"):
            source = firmware / "segacd" / name
            links.append((source, save_root / "config/retroarch/system" / name))
    elif system_id == "sega-saturn":
        for name in ("sega_101.bin", "mpr-17933.bin"):
            source = firmware / "saturn" / name
            links.append((source, save_root / "config/retroarch/system" / name))
    elif system_id == "pc-engine":
        source = firmware / "pcengine/syscard3.pce"
        links.append((source, save_root / "config/retroarch/system/syscard3.pce"))
    elif system_id == "amiga":
        source_root = firmware / "amiga"
        if source_root.is_dir():
            for source in source_root.iterdir():
                if source.is_file():
                    links.append((source, save_root / "config/retroarch/system" / source.name))
    for source, destination in links:
        if not source.is_file():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or destination.exists():
            destination.unlink()
        destination.symlink_to(source)


def _prepare_cemu_config(save_root: Path) -> Path:
    """Seed a controller-ready, Vulkan Cemu profile inside the game save root."""
    cemu_root = save_root / "data/Cemu"
    config_root = save_root / "config/Cemu"
    mlc_root = cemu_root / "mlc01"
    # Cemu's Linux build reads controller profiles from XDG_CONFIG_HOME.
    controller_root = config_root / "controllerProfiles"
    controller_root.mkdir(parents=True, exist_ok=True)
    mlc_root.mkdir(parents=True, exist_ok=True)
    settings = cemu_root / "settings.xml"
    settings.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<content>
  <mlc_path>{mlc}</mlc_path>
  <permanent_storage>true</permanent_storage>
  <use_discord_presence>false</use_discord_presence>
  <fullscreen_menubar>false</fullscreen_menubar>
  <check_update>false</check_update>
  <fullscreen>true</fullscreen>
  <disable_screensaver>true</disable_screensaver>
  <play_boot_sound>false</play_boot_sound>
  <console_language>1</console_language>
  <Graphic>
    <api>1</api><VSync>1</VSync><GX2DrawdoneSync>true</GX2DrawdoneSync>
    <UpscaleFilter>2</UpscaleFilter><DownscaleFilter>0</DownscaleFilter>
    <FullscreenScaling>0</FullscreenScaling><AsyncCompile>true</AsyncCompile>
    <vkAccurateBarriers>true</vkAccurateBarriers>
  </Graphic>
  <Audio>
    <api>3</api><delay>2</delay><TVChannels>1</TVChannels>
    <PadChannels>1</PadChannels><TVVolume>100</TVVolume><PadVolume>0</PadVolume>
    <TVDevice>default</TVDevice>
  </Audio>
  <Hotkeys><ExitFullscreen>0 -1</ExitFullscreen><ExitApplication>27 -1</ExitApplication></Hotkeys>
</content>
""".format(mlc=html.escape(str(mlc_root))),
        encoding="utf-8",
    )
    # Cemu releases have used both XDG data and config locations.  Keep the
    # same settings in both without sharing them between games/profiles.
    config_root.mkdir(parents=True, exist_ok=True)
    config_settings = config_root / "settings.xml"
    config_settings.write_text(settings.read_text(encoding="utf-8"), encoding="utf-8")

    library_name = ctypes.util.find_library("SDL2") or "libSDL2-2.0.so.0"
    try:
        sdl = ctypes.CDLL(library_name)
        class Guid(ctypes.Structure):
            _fields_ = [("data", ctypes.c_uint8 * 16)]
        sdl.SDL_Init.argtypes = [ctypes.c_uint32]
        sdl.SDL_Init.restype = ctypes.c_int
        sdl.SDL_NumJoysticks.restype = ctypes.c_int
        sdl.SDL_IsGameController.argtypes = [ctypes.c_int]
        sdl.SDL_IsGameController.restype = ctypes.c_int
        sdl.SDL_GameControllerNameForIndex.argtypes = [ctypes.c_int]
        sdl.SDL_GameControllerNameForIndex.restype = ctypes.c_char_p
        sdl.SDL_JoystickGetDeviceGUID.argtypes = [ctypes.c_int]
        sdl.SDL_JoystickGetDeviceGUID.restype = Guid
        sdl.SDL_JoystickGetGUIDString.argtypes = [Guid, ctypes.c_char_p, ctypes.c_int]
        selected: tuple[str, str] | None = None
        if sdl.SDL_Init(0x00000200 | 0x00001000 | 0x00002000) == 0:
            try:
                for index in range(sdl.SDL_NumJoysticks()):
                    if not sdl.SDL_IsGameController(index):
                        continue
                    guid = sdl.SDL_JoystickGetDeviceGUID(index)
                    guid_text = ctypes.create_string_buffer(64)
                    sdl.SDL_JoystickGetGUIDString(guid, guid_text, len(guid_text))
                    raw_name = sdl.SDL_GameControllerNameForIndex(index)
                    name = raw_name.decode("utf-8", "replace") if raw_name else "SDL Game Controller"
                    # Cemu's SDL migration code stores GUID first, then player.
                    selected = (f"{guid_text.value.decode('ascii')}_0", name)
                    break
            finally:
                sdl.SDL_Quit()
    except (AttributeError, OSError):
        selected = None
    if selected is not None:
        uuid, display_name = selected
        mappings = (
            (1, 1), (2, 0), (3, 3), (4, 2), (5, 9), (6, 10), (7, 42), (8, 43),
            (9, 6), (10, 4), (11, 11), (12, 12), (13, 13), (14, 14), (15, 7),
            (16, 8), (17, 45), (18, 39), (19, 44), (20, 38), (21, 47), (22, 41),
            (23, 46), (24, 40),
        )
        entries = "\n".join(
            f"      <entry><mapping>{mapping}</mapping><button>{button}</button></entry>"
            for mapping, button in mappings
        )
        profile = controller_root / "controller0.xml"
        profile.write_text(
            f"""<?xml version="1.0" encoding="UTF-8"?>
<emulated_controller><type>Wii U GamePad</type><toggle_display>0</toggle_display><controller>
  <api>SDLController</api><uuid>{html.escape(uuid)}</uuid>
  <display_name>{html.escape(display_name)}</display_name><rumble>0.5</rumble>
  <axis><deadzone>0.15</deadzone><range>1</range></axis>
  <rotation><deadzone>0.15</deadzone><range>1</range></rotation>
  <trigger><deadzone>0.05</deadzone><range>1</range></trigger>
  <mappings>\n{entries}\n  </mappings>
</controller></emulated_controller>
""",
            encoding="utf-8",
        )
        # Retain a compatibility copy for older Cemu AppImages which looked in
        # XDG_DATA_HOME before the current XDG config layout was standardized.
        legacy_root = cemu_root / "controllerProfiles"
        legacy_root.mkdir(parents=True, exist_ok=True)
        (legacy_root / profile.name).write_text(profile.read_text(encoding="utf-8"), encoding="utf-8")
    return settings


def _run_cemu(command: list[str], working_directory: Path, environment: dict[str, str], log) -> int:
    """Keep ownership of Cemu after its AppImage wrapper forks.

    The dashboard remains blocked until the complete process group exits. A
    held Xbox View+Menu combination terminates that group cleanly.
    """
    process = subprocess.Popen(
        command, cwd=working_directory, env=environment,
        stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    group_id = process.pid
    joystick = None
    combo_started: float | None = None
    pygame_module = None
    try:
        try:
            import pygame

            pygame_module = pygame
            pygame.joystick.init()
            if pygame.joystick.get_count():
                joystick = pygame.joystick.Joystick(0)
                joystick.init()
        except Exception:
            joystick = None
        while True:
            # Reap the short-lived AppImage wrapper so it cannot remain as a
            # zombie that falsely keeps the process group alive forever.
            process.poll()
            try:
                os.killpg(group_id, 0)
            except ProcessLookupError:
                break
            if pygame_module is not None:
                try:
                    pygame_module.event.pump()
                    held = bool(
                        joystick is not None and joystick.get_numbuttons() > 7
                        and joystick.get_button(6) and joystick.get_button(7)
                    )
                except Exception:
                    held = False
                if held:
                    combo_started = combo_started or time.monotonic()
                    if time.monotonic() - combo_started >= 0.75:
                        os.killpg(group_id, signal.SIGTERM)
                        deadline = time.monotonic() + 2.0
                        while time.monotonic() < deadline:
                            try:
                                os.killpg(group_id, 0)
                            except ProcessLookupError:
                                break
                            time.sleep(0.05)
                        else:
                            os.killpg(group_id, signal.SIGKILL)
                        return 0
                else:
                    combo_started = None
            time.sleep(0.025)
        return process.poll() or 0
    finally:
        if pygame_module is not None:
            try:
                pygame_module.joystick.quit()
            except Exception:
                pass


def _duckstation_serial(entry: dict) -> str:
    serial = str(entry.get("serial") or entry.get("disc_serial") or "").replace("-", "").upper()
    match = re.fullmatch(r"([A-Z]{4})(\d{5})", serial)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    if str(entry.get("title", "")).strip().casefold() == "beyond the beyond":
        return "SCUS-94702"
    return ""


def _prepare_duckstation_cheats(save_root: Path, serial: str, cheats: list[Cheat]) -> None:
    """Export and enable PulseArc's selected cheats for modern DuckStation."""
    enabled = [cheat for cheat in cheats if cheat.enabled]
    if not serial:
        return
    for root in (save_root / "data/duckstation", save_root / "config/duckstation"):
        export_duckstation(enabled, root / "cheats" / f"{serial}.cht")

    # AppImage releases have searched either XDG data or XDG config for
    # per-game INIs. Keep identical settings in both locations. Repeated
    # Enable keys are DuckStation's string-list format.
    for root in (save_root / "data/duckstation", save_root / "config/duckstation"):
        game_settings = root / "gamesettings" / f"{serial}.ini"
        game_settings.parent.mkdir(parents=True, exist_ok=True)
        retained: list[str] = []
        skipping_cheats = False
        if game_settings.is_file():
            for line in game_settings.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("[") and line.endswith("]"):
                    skipping_cheats = line[1:-1].strip().casefold() == "cheats"
                    if skipping_cheats:
                        continue
                if not skipping_cheats:
                    retained.append(line)
        while retained and not retained[-1].strip():
            retained.pop()
        retained.extend(["", "[Cheats]", "EnableCheats = true", "LoadCheatsFromDatabase = false"])
        retained.extend(f"Enable = {cheat.name}" for cheat in enabled)
        temporary = game_settings.with_suffix(".ini.tmp")
        temporary.write_text("\n".join(retained) + "\n", encoding="utf-8")
        temporary.replace(game_settings)


def _controller_profile(entry: dict) -> Path | None:
    value = str(entry.get("controller_profile", "")).strip()
    if not value:
        return None
    root = Path(str(entry["source_root"])).resolve()
    profile = Path(value).resolve()
    try:
        profile.relative_to(root)
    except ValueError as exc:
        raise ValueError("controller profile escaped the mounted media root") from exc
    if profile.suffix.lower() not in {".amgp", ".xml"} or not profile.is_file():
        raise ValueError("controller profile is missing or unsupported")
    return validate_antimicrox_profile(profile)


def _policy() -> GraphicsPolicy:
    path = Path("/run/pulsearc/graphics.json")
    if not path.exists():
        return GraphicsPolicy("x11", "wined3d", "unsupported", "safe default")
    return GraphicsPolicy(**json.loads(path.read_text(encoding="utf-8")))


def _entry(content_id: str) -> dict:
    entries = json.loads(INDEX.read_text(encoding="utf-8"))
    result = next((item for item in entries if item["content_id"] == content_id), None)
    if result is None:
        raise KeyError(f"content ID not present: {content_id}")
    return result


def launch(content_id: str, profile_id: str) -> int:
    entry = _entry(content_id)
    system_id = str(entry["platform"])
    registry = RuntimeRegistry.load(REGISTRY)
    if system_id not in registry.systems:
        raise RuntimeError(f"{system_id} still requires disc-content resolution")
    installed = {runner.executable for runner in registry.runners.values() if Path(runner.executable).exists()}
    plan = create_launch_plan(
        entry["path"], system_id, content_id, profile_id, registry, _policy(), STATE, installed,
    )
    if (
        system_id == "playstation-2"
        and stat.S_ISBLK(Path(entry["path"]).stat().st_mode)
    ):
        command = list(plan.command)
        content_index = command.index(str(Path(entry["path"]).resolve()))
        command[content_index:content_index + 1] = ["-disc", str(Path(entry["path"]).resolve())]
        plan = type(plan)(
            plan.runner_id, tuple(command), plan.environment,
            plan.working_directory, plan.save_root,
        )
    plan.save_root.mkdir(parents=True, exist_ok=True)
    _prepare_firmware(system_id, plan.save_root)
    if plan.runner_id.startswith("retroarch-"):
        cheats = load_cheats(cheat_file(STATE, profile_id, system_id, content_id))
        _prepare_retroarch_config(plan.save_root, plan.runner_id, Path(entry["path"]), cheats)
    elif plan.runner_id == "duckstation":
        _prepare_duckstation_config(plan.save_root)
        serial = _duckstation_serial(entry)
        if serial:
            cheats = load_cheats(cheat_file(STATE, profile_id, system_id, content_id))
            _prepare_duckstation_cheats(plan.save_root, serial, cheats)
    elif plan.runner_id == "pcsx2":
        _prepare_pcsx2_config(plan.save_root)
    elif plan.runner_id == "rpcs3":
        cheats = load_cheats(cheat_file(STATE, profile_id, system_id, content_id))
        _prepare_rpcs3_config(plan.save_root, cheats, str(entry.get("serial", "")))
    elif plan.runner_id == "cemu":
        _prepare_cemu_config(plan.save_root)
    log_dir = plan.save_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(plan.environment)
    # PulseArc owns runtime integration.  Never hand an AppImage to a desktop
    # integration helper, which can display shortcut/install prompts over the
    # controller-only shell.
    if any(str(part).endswith(".AppImage") for part in plan.command):
        environment["APPIMAGE_EXTRACT_AND_RUN"] = "1"
        environment["APPIMAGELAUNCHER_DISABLE"] = "1"
    if plan.runner_id == "cemu":
        environment["SDL_GAMECONTROLLER_USE_BUTTON_LABELS"] = "0"
    controller_profile = _controller_profile(entry)
    (log_dir / "last-plan.json").write_text(json.dumps({
        "runner_id": plan.runner_id,
        "command": plan.command,
        "environment": plan.environment,
        "working_directory": str(plan.working_directory),
    }, indent=2), encoding="utf-8")
    mapper: subprocess.Popen | None = None
    with (log_dir / "last-run.log").open("w", encoding="utf-8") as log:
        try:
            if controller_profile is not None:
                mapper = subprocess.Popen(
                    ["/usr/bin/antimicrox", "--tray", str(controller_profile)],
                    cwd=plan.working_directory, env=environment,
                    stdout=log, stderr=subprocess.STDOUT,
                )
            if plan.runner_id == "cemu":
                return_code = _run_cemu(
                    list(plan.command), plan.working_directory, environment, log,
                )
            else:
                process = subprocess.run(
                    list(plan.command), cwd=plan.working_directory, env=environment,
                    stdout=log, stderr=subprocess.STDOUT, check=False,
                )
                return_code = process.returncode
        finally:
            if mapper is not None and mapper.poll() is None:
                mapper.terminate()
                try:
                    mapper.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    mapper.kill()
    return return_code


def manager_json(manager: str, profile_id: str) -> str:
    if manager == "saves":
        entries = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else []
        by_content_id = {str(entry.get("content_id", "")): entry for entry in entries}
        payload = [
            {
                **asdict(record),
                "path": str(record.path),
                "title": str(by_content_id.get(record.content_id, {}).get("title", record.content_id)),
                "platform": str(by_content_id.get(record.content_id, {}).get("platform", "unknown")),
            }
            for record in inventory(STATE, profile_id)
        ]
        return json.dumps(payload)
    if manager == "cheats":
        entries = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else []
        for entry in entries:
            _sync_rpcs3_cheats(entry, profile_id)
        payload = []
        for entry in entries:
            path = cheat_file(STATE, profile_id, str(entry["platform"]), str(entry["content_id"]))
            cheats = load_cheats(path)
            payload.append({
                "content_id": entry["content_id"], "title": entry["title"],
                "platform": entry["platform"], "cheat_count": len(cheats),
                "enabled_count": sum(item.enabled for item in cheats),
            })
        return json.dumps(payload)
    raise ValueError(f"unknown manager: {manager}")


def cheat_json(content_id: str, profile_id: str) -> str:
    entry = _entry(content_id)
    _sync_rpcs3_cheats(entry, profile_id)
    path = cheat_file(STATE, profile_id, str(entry["platform"]), content_id)
    return json.dumps([asdict(item) for item in load_cheats(path)])


def toggle_cheat(content_id: str, index: int, profile_id: str) -> str:
    entry = _entry(content_id)
    path = cheat_file(STATE, profile_id, str(entry["platform"]), content_id)
    return json.dumps(asdict(set_cheat_enabled(path, index)))


def main() -> None:
    parser = argparse.ArgumentParser()
    subcommands = parser.add_subparsers(dest="command", required=True)
    launch_parser = subcommands.add_parser("launch")
    launch_parser.add_argument("content_id")
    launch_parser.add_argument("--profile", default="default")
    manager_parser = subcommands.add_parser("manager-json")
    manager_parser.add_argument("manager", choices=("saves", "cheats"))
    manager_parser.add_argument("--profile", default="default")
    cheat_parser = subcommands.add_parser("cheat-json")
    cheat_parser.add_argument("content_id")
    cheat_parser.add_argument("--profile", default="default")
    toggle_parser = subcommands.add_parser("cheat-toggle")
    toggle_parser.add_argument("content_id")
    toggle_parser.add_argument("index", type=int)
    toggle_parser.add_argument("--profile", default="default")
    args = parser.parse_args()
    if args.command == "launch":
        raise SystemExit(launch(args.content_id, args.profile))
    if args.command == "manager-json":
        print(manager_json(args.manager, args.profile))
    elif args.command == "cheat-json":
        print(cheat_json(args.content_id, args.profile))
    elif args.command == "cheat-toggle":
        print(toggle_cheat(args.content_id, args.index, args.profile))


if __name__ == "__main__":
    main()
