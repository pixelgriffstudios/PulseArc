#!/usr/bin/env python3
"""PulseArc native fullscreen shell.

This is a small SDL2-backed interface built with Pygame.  It deliberately does
not depend on a desktop toolkit or game engine.  The shell owns the display,
maps Xbox-style controllers directly, and delegates media discovery and game
launching to pulsearc-core.
"""

from __future__ import annotations

import functools
import json
import hashlib
import math
import os
import signal
import socket
import subprocess
import shutil
import sys
import time
import tempfile
import threading
import re
import urllib.parse
import urllib.request
import zipfile
from array import array
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")

import pygame

from pulsearc_network import (
    bluetooth_devices,
    connect_wifi,
    disconnect_bluetooth,
    pair_or_connect_bluetooth,
    wifi_networks,
)
from pulsearc_tv import (
    BUILTIN_TV_SOURCES,
    FREE_STREAMING_APPS,
    fetch_us_online_epg,
    fetch_source,
    fetch_xtream_short_epg,
    fetch_xtream_xmltv_epg,
    import_sources_from_media,
    load_saved_sources,
    online_epg_feed_warning,
    public_source_label,
    save_sources,
)
from pulsearc_personalization import (
    MAX_PROFILES,
    Theme,
    discover_themes,
    import_theme_archive,
    load_profiles,
    save_profiles,
)
from pulsearc_archive_import import ArchiveItem, discover_archives, install_archive


LOGICAL_SIZE = (1280, 720)
BOOT_SECONDS = 4.2
LIBRARY_PATH = Path("/run/pulsearc/library.json")
OPTICAL_ENTRY_PATH = Path("/run/pulsearc/optical-entry.json")
COVERS_PATH = Path.home() / ".cache/pulsearc/covers.json"
SYNOPSES_PATH = Path.home() / ".cache/pulsearc/synopses.json"
GRAPHICS_PATH = Path("/run/pulsearc/graphics.json")
SSH_CREDENTIAL_PATH = Path("/var/lib/pulsearc/firstboot-ssh.txt")
SETTINGS_PATH = Path("/var/lib/pulsearc/settings.json")
PROFILES_PATH = Path("/var/lib/pulsearc/profiles/profiles.json")
ACTIVE_PROFILE_PATH = Path("/var/lib/pulsearc/profiles/active-profile")
USER_THEMES_PATH = Path.home() / ".local/share/pulsearc/themes"
BUILTIN_THEMES_PATH = Path(__file__).resolve().parent / "themes"
PROFILE_AVATARS_PATH = Path(__file__).resolve().parent / "assets/profile-avatars"
REMOVABLE_ROOT = Path("/run/media/gamer")
DOWNLOADS_ROOT = Path.home() / "Downloads"
IMPORTED_GAMES_ROOT = Path("/var/lib/pulsearc/library/games/imported")
TV_DATA_ROOT = Path.home() / ".local/share/pulsearc/tv"
TV_SOURCES_PATH = TV_DATA_ROOT / "sources.json"
TV_CACHE_ROOT = Path.home() / ".cache/pulsearc/tv"
TV_ARTWORK_ROOT = TV_CACHE_ROOT / "artwork"
DISC_DATABASE_ROOT = Path.home() / ".local/share/pulsearc/metadata/disc-databases"
THREE_D_LIBRARY_PATHS = (
    Path.home() / ".local/share/pulsearc/native-ui/pulsearc_3d_library.py",
    Path("/usr/share/pulsearc/native-ui/pulsearc_3d_library.py"),
)
THREE_D_SELECTION_PATH = Path("/run/pulsearc/3d-selection.json")
PULSEARC_CORE_PATHS = (
    Path.home() / ".local/share/pulsearc/core",
    Path("/usr/lib/pulsearc/core"),
    Path("/usr/share/pulsearc/core"),
)

CYAN = (80, 232, 255)
PINK = (255, 85, 200)
PURPLE = (200, 139, 255)
WHITE = (235, 241, 255)
MUTED = (172, 190, 230)
GREEN = (103, 217, 181)
PANEL = (10, 13, 31, 225)
DISABLED = (70, 76, 103)

MENU = (
    ("PLAY", "Browse inserted USB, SD, CD, DVD, and internal games"),
    ("LIBRARY", "Games installed on internal storage"),
    ("3D PLAZA", "Explore the video store, parking plaza, theater, arcade, and internet cafe"),
    ("MUSIC", "Audio CDs, MP3/WAV playback, and ProjectM visuals"),
    ("TV", "Free live channels, IPTV providers, M3U playlists, and streaming apps"),
    ("APPS", "Steam, cloud gaming, safe web access, and downloaded media"),
    ("SAVES", "Back up, restore, copy, and delete profile saves"),
    ("CHEATS", "Manage disabled-by-default cheats per game"),
    ("CONTROLLERS", "Xbox-style defaults and per-game layouts"),
    ("SETTINGS", "Display, audio, network, artwork, and storage"),
    ("EXTRAS", "Optional PulseArc features and future add-ons"),
    ("POWER", "Soft restart, restart the computer, or shut down"),
)

RADIO_STATIONS = (
    {
        "genre": "ROCK",
        "name": "Rock 181",
        "url": "https://listen.181fm.com/181-rock_128k.mp3",
    },
    {
        "genre": "ROCK / POP",
        "name": "SomaFM Indie Pop Rocks!",
        "url": "https://ice2.somafm.com/indiepop-128-mp3",
    },
    {
        "genre": "POP",
        "name": "Power 181 (Top 40)",
        "url": "https://listen.181fm.com/181-power_128k.mp3",
    },
    {
        "genre": "HIP-HOP / R&B",
        "name": "The Beat",
        "url": "https://listen.181fm.com/181-beat_128k.mp3",
    },
    {
        "genre": "80'S",
        "name": "Awesome 80's",
        "url": "https://listen.181fm.com/181-awesome80s_128k.mp3",
    },
    {
        "genre": "80'S NEW WAVE",
        "name": "SomaFM Underground 80s",
        "url": "https://ice2.somafm.com/u80s-128-mp3",
    },
)

ONSCREEN_KEYS = tuple(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "0123456789"
    "!@#$%^&*()-_=+."
) + ("BACKSPACE", "CONNECT", "CANCEL")
ONSCREEN_COLUMNS = 10
PROFILE_KEYS = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -_") + ("BACKSPACE", "SAVE", "CANCEL")

BIOS_REQUIREMENTS = (
    ("PLAYSTATION", "scph5501.bin", "ps1", ("scph5501.bin",)),
    ("PLAYSTATION 2", "scph10000.bin", "ps2", ("scph10000.bin",)),
    ("WII U / CEMU", "keys.txt", "wiiu", ("keys.txt",)),
    ("PLAYSTATION 3", "PS3UPDAT.PUP", "ps3", ("ps3updat.pup",)),
    ("PS3 DISC KEYS", ".key / .dkey archive", "ps3-keys", ()),
    ("DREAMCAST BOOT", "dc_boot.bin", "dreamcast", ("dc_boot.bin",)),
    ("DREAMCAST FLASH", "dc_flash.bin", "dreamcast", ("dc_flash.bin",)),
    ("SEGA CD (USA)", "bios_CD_U.bin", "segacd", ("bios_cd_u.bin",)),
    ("SEGA SATURN", "sega_101.bin or mpr-17933.bin", "saturn", ("sega_101.bin", "mpr-17933.bin")),
    ("PC ENGINE CD", "syscard3.pce", "pcengine", ("syscard3.pce",)),
    ("AMIGA", "Kickstart ROM", "amiga", ("kick34005.a500", "kick40068.a1200", "kick40068.a4000")),
)


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def _normalize_ps3_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Repair PS3 rows produced by early scanners that treated EBOOT.BIN as generic optical media."""
    path = Path(str(entry.get("path", "")))
    parts = tuple(part.casefold() for part in path.parts)
    is_ps3_eboot = (
        path.name.casefold() == "eboot.bin"
        and len(parts) >= 3
        and parts[-2] == "usrdir"
        and parts[-3] == "ps3_game"
    )
    hints_ps3 = (
        str(entry.get("runner", "")).casefold() == "rpcs3"
        or "playstation-3" in parts
        or is_ps3_eboot
    )
    if not hints_ps3:
        return entry
    normalized = dict(entry)
    normalized["platform"] = "playstation-3"
    normalized["runner"] = "rpcs3"
    normalized["media_kind"] = "disc-image"
    if is_ps3_eboot and str(normalized.get("title", "")).casefold() in {"", "eboot"}:
        game_root = path.parents[2]
        normalized["title"] = " ".join(game_root.name.replace("_", " ").replace("-", " ").split()).title()
    return normalized


def pulsearc_control_env() -> dict[str, str]:
    """Return an environment that can import the installed PulseArc backend.

    Developer/live deployments keep the core below the gamer account while
    image installs use /usr/lib.  Keeping both locations in PYTHONPATH avoids
    silently empty manager screens after either deployment style.
    """
    existing = os.environ.get("PYTHONPATH", "")
    paths = [str(path) for path in PULSEARC_CORE_PATHS if path.is_dir()]
    if existing:
        paths.append(existing)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))
    return environment


def local_ipv4() -> str:
    addresses: list[str] = []
    try:
        result = subprocess.run(
            ["/usr/bin/ip", "-j", "-4", "address", "show", "scope", "global"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
        for interface in json.loads(result.stdout or "[]"):
            for info in interface.get("addr_info", []):
                address = str(info.get("local", ""))
                if address and address not in addresses:
                    addresses.append(address)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    if not addresses:
        try:
            addresses = [socket.gethostbyname(socket.gethostname())]
        except OSError:
            pass
    return addresses[0] if addresses else "pending network"


def ssh_password() -> str:
    try:
        for line in SSH_CREDENTIAL_PATH.read_text(encoding="utf-8").splitlines():
            if line.startswith("Password: "):
                return line.removeprefix("Password: ").strip()
    except OSError:
        pass
    return "generating"


def internal_free_space() -> str:
    try:
        free = shutil.disk_usage("/var/lib/pulsearc").free
    except OSError:
        return "space unknown"
    return f"{free / (1024 ** 3):.1f} GB free"


def is_music_entry(item: dict[str, Any]) -> bool:
    """Accept both current and early scanner field names for audio entries."""
    media_kind = str(item.get("platform") or item.get("system") or item.get("media_type") or "").lower()
    if media_kind in {"music", "audio"}:
        return True
    return Path(str(item.get("path", ""))).suffix.lower() in {".mp3", ".wav", ".flac", ".ogg", ".m4a"}


def is_movie_entry(item: dict[str, Any]) -> bool:
    media_kind = str(item.get("media_kind") or item.get("platform") or "").lower()
    if media_kind in {"movie", "video", "dvd-video"}:
        return True
    return Path(str(item.get("path", ""))).suffix.lower() in {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts"}


def is_installed_game(item: dict[str, Any]) -> bool:
    """Return true only for game content stored in the internal library."""
    source_root = Path(str(item.get("source_root", "")))
    path = Path(str(item.get("path", "")))
    internal_root = Path("/var/lib/pulsearc/library")
    local = source_root.is_relative_to(internal_root) or path.is_relative_to(internal_root / "games")
    return local and not is_music_entry(item) and not is_movie_entry(item)


def is_internal_content(item: dict[str, Any]) -> bool:
    """Content shown in the 3D store: installed games and installed movies."""
    source_root = Path(str(item.get("source_root", "")))
    path = Path(str(item.get("path", "")))
    internal_root = Path("/var/lib/pulsearc/library")
    local = source_root.is_relative_to(internal_root) or path.is_relative_to(internal_root)
    return local and not is_music_entry(item)


def is_external_entry(item: dict[str, Any]) -> bool:
    """Play is the removable-media surface; internal games belong in Library."""
    return not is_installed_game(item) and not str(item.get("path", "")).startswith("/var/lib/pulsearc/library/")


def _disc_volume(path: Path, root: Path) -> Path:
    """Return the mounted volume that contains a discovered optical marker."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path.parent
    return root / relative.parts[0] if len(relative.parts) > 1 else root


def _unescape_mount_path(value: str) -> str:
    """Decode the small set of octal escapes used by /proc/mounts."""
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _optical_volumes(root: Path) -> list[Path]:
    """Return mounted optical volumes without walking unrelated USB media."""
    volumes: list[Path] = []
    try:
        root_resolved = root.resolve()
        for line in Path("/proc/mounts").read_text(encoding="utf-8", errors="replace").splitlines():
            fields = line.split()
            if len(fields) < 3 or fields[2].lower() not in {"iso9660", "udf"}:
                continue
            candidate = Path(_unescape_mount_path(fields[1]))
            try:
                candidate.resolve().relative_to(root_resolved)
            except (OSError, ValueError):
                continue
            if candidate.is_dir():
                volumes.append(candidate)
    except OSError:
        pass
    if volumes:
        return sorted(set(volumes), key=lambda item: str(item).casefold())

    # Unit tests and manually mounted development media do not necessarily
    # appear in /proc/mounts.  Treat each immediate child as one volume, while
    # still avoiding the previous recursive walk of all removable storage.
    try:
        children = [item for item in root.iterdir() if item.is_dir()]
    except OSError:
        return []
    return children or ([root] if root.is_dir() else [])


def _volume_files(volume: Path) -> list[Path]:
    try:
        return [item for item in volume.iterdir() if item.is_file()]
    except OSError:
        return []


@functools.lru_cache(maxsize=512)
def _read_disc_title_database(database: Path, serial: str) -> str:
    """Read one title from DuckStation/PCSX2's bundled YAML without PyYAML."""
    if not database.is_file():
        return ""
    header = re.compile(rf'^\s*"?{re.escape(serial)}"?\s*:\s*$', re.IGNORECASE)
    name = re.compile(r'^\s{2}name\s*:\s*["\']?(.*?)["\']?\s*$')
    in_record = False
    try:
        with database.open("r", encoding="utf-8", errors="replace") as source:
            for line in source:
                if not in_record:
                    in_record = header.match(line.rstrip()) is not None
                    continue
                if line and not line[0].isspace():
                    break
                match = name.match(line.rstrip())
                if match:
                    return match.group(1).strip().strip('"\'')
    except OSError:
        pass
    return ""


def _extract_disc_database(platform: str) -> Path | None:
    """Cache the title database already bundled inside the installed emulator."""
    if platform == "playstation":
        image_candidates = (
            Path.home() / ".local/share/pulsearc/runners/duckstation/duckstation.AppImage",
            Path("/usr/lib/pulsearc/runners/duckstation/duckstation.AppImage"),
        )
        relative = Path("usr/bin/resources/gamedb.yaml")
        destination = DISC_DATABASE_ROOT / "duckstation-gamedb.yaml"
    else:
        image_candidates = (Path("/usr/lib/pulsearc/runners/pcsx2/pcsx2.AppImage"),)
        relative = Path("usr/bin/resources/GameIndex.yaml")
        destination = DISC_DATABASE_ROOT / "pcsx2-game-index.yaml"
    if destination.is_file():
        return destination
    image = next((candidate for candidate in image_candidates if candidate.is_file()), None)
    if image is None:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="pulsearc-disc-db-") as temporary:
            subprocess.run(
                [str(image), "--appimage-extract"],
                cwd=temporary,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=False,
            )
            extracted = Path(temporary) / "squashfs-root" / relative
            if not extracted.is_file():
                return None
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging = destination.with_suffix(".yaml.tmp")
            shutil.copy2(extracted, staging)
            staging.replace(destination)
    except (OSError, subprocess.SubprocessError):
        return None
    return destination


def _playstation_disc_title(platform: str, serial: str) -> str:
    database = _extract_disc_database(platform)
    return _read_disc_title_database(database, serial) if database is not None else ""


def _iso9660_root_files(device: Path) -> tuple[str, dict[str, bytes]]:
    """Read a few ISO9660 root files directly, without waiting for a mount."""
    descriptor = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    try:
        sector = 2048
        primary = os.pread(descriptor, sector, 16 * sector)
        if len(primary) < sector or primary[1:6] != b"CD001":
            return "", {}
        volume_id = primary[40:72].decode("ascii", errors="replace").strip()
        block_size = int.from_bytes(primary[128:130], "little") or sector
        root_record = primary[156:190]
        if len(root_record) < 34:
            return volume_id, {}
        root_extent = int.from_bytes(root_record[2:6], "little")
        root_size = min(int.from_bytes(root_record[10:14], "little"), 256 * 1024)
        directory = os.pread(descriptor, root_size, root_extent * block_size)
        records: dict[str, tuple[int, int]] = {}
        offset = 0
        while offset < len(directory):
            length = directory[offset]
            if length == 0:
                offset = ((offset // block_size) + 1) * block_size
                continue
            record = directory[offset:offset + length]
            if len(record) < 34:
                break
            name_size = record[32]
            name = record[33:33 + name_size].decode("ascii", errors="replace").upper()
            if name not in {"\x00", "\x01"}:
                records[name.removesuffix(";1")] = (
                    int.from_bytes(record[2:6], "little"),
                    int.from_bytes(record[10:14], "little"),
                )
            offset += length
        wanted: dict[str, bytes] = {}
        for name, (extent, size) in records.items():
            if name == "SYSTEM.CNF" or re.fullmatch(r"[A-Z]{4}[_-]\d{3}[.]\d{2}", name):
                wanted[name] = os.pread(descriptor, min(size, 64 * 1024), extent * block_size)
        return volume_id, wanted
    finally:
        os.close(descriptor)


def _direct_playstation_disc(device: Path = Path("/dev/sr0")) -> dict[str, Any] | None:
    """Identify PS1/PS2 media from its first filesystem sectors in milliseconds."""
    try:
        label, files = _iso9660_root_files(device)
    except OSError:
        return None
    document = files.get("SYSTEM.CNF", b"").decode("ascii", errors="replace")
    boot = re.search(
        r"(?im)^\s*BOOT(2)?\s*=.*?([A-Z]{4})[_-](\d{3})[.]?(\d{2})",
        document,
    )
    if boot is not None:
        platform = "playstation-2" if boot.group(1) else "playstation"
        serial = f"{boot.group(2).upper()}-{boot.group(3)}{boot.group(4)}"
    else:
        serial_name = next(
            (name for name in files if re.fullmatch(r"[A-Z]{4}[_-]\d{3}[.]\d{2}", name)),
            "",
        )
        match = re.fullmatch(r"([A-Z]{4})[_-](\d{3})[.](\d{2})", serial_name)
        if match is None:
            return None
        platform = "playstation"
        serial = f"{match.group(1).upper()}-{match.group(2)}{match.group(3)}"
    generic_labels = {"cdrom", "dvd", "disc", "disk", "media", "sr0"}
    display_label = " ".join(label.replace("_", " ").split()).strip()
    if not display_label or display_label.casefold() in generic_labels:
        display_label = "PlayStation 2 Game" if platform == "playstation-2" else "PlayStation Game"
    title = _playstation_disc_title(platform, serial) or display_label
    identity = hashlib.sha256(f"{platform}:{serial}".encode("ascii")).hexdigest()[:24]
    return {
        "content_id": identity,
        "title": title,
        "platform": platform,
        "runner": "pcsx2" if platform == "playstation-2" else "duckstation",
        "media_kind": "disc-image",
        "path": str(device),
        "source_root": str(device),
        "read_only": True,
        "disc_serial": serial,
    }


def detected_dvd_video(root: Path = REMOVABLE_ROOT) -> dict[str, Any] | None:
    """Return a temporary library entry for a mounted DVD-Video volume."""
    if not root.is_dir():
        return None
    marker = None
    for volume in _optical_volumes(root):
        try:
            video_directory = next(
                (item for item in volume.iterdir() if item.is_dir() and item.name.upper() == "VIDEO_TS"),
                None,
            )
            if video_directory is not None:
                marker = next(
                    (item for item in video_directory.iterdir()
                     if item.is_file() and item.name.upper().removesuffix(";1") == "VIDEO_TS.IFO"),
                    None,
                )
        except OSError:
            marker = None
        if marker is not None:
            break
    if marker is None:
        return None
    device = next((path for path in ("/dev/sr0", "/dev/cdrom") if Path(path).exists()), "/dev/sr0")
    raw_title = marker.parents[1].name or "DVD Movie"
    display_title = " ".join(raw_title.replace("_", " ").split()).title()
    identity = hashlib.sha256(display_title.casefold().encode("utf-8")).hexdigest()[:16]
    return {
        "content_id": f"pulsearc-dvd-video-{identity}",
        "title": display_title,
        "platform": "dvd-video",
        "runner": "vlc",
        "media_kind": "dvd-video",
        "path": device,
        "source_root": str(marker.parents[1]),
        "read_only": True,
    }


def detected_playstation_disc(root: Path = REMOVABLE_ROOT) -> dict[str, Any] | None:
    """Identify PS1/PS2 discs directly first, with mounted media as fallback."""
    direct = _direct_playstation_disc()
    if direct is not None:
        return direct
    if not root.is_dir():
        return None
    marker = None
    serial_marker = None
    volume = None
    volume_files: list[Path] = []
    serial_pattern = re.compile(r"^([A-Z]{4})[_-](\d{3})[.](\d{2})(?:;1)?$", re.IGNORECASE)
    for candidate_volume in _optical_volumes(root):
        candidate_files = _volume_files(candidate_volume)
        candidate_marker = next(
            (path for path in candidate_files
             if path.name.upper().removesuffix(";1") == "SYSTEM.CNF"),
            None,
        )
        candidate_serial = next(
            (path for path in candidate_files if serial_pattern.match(path.name)),
            None,
        )
        if candidate_marker is not None or candidate_serial is not None:
            marker = candidate_marker
            serial_marker = candidate_marker or candidate_serial
            volume = candidate_volume
            volume_files = candidate_files
            break
    if serial_marker is None or volume is None:
        return None
    boot = None
    if marker is not None:
        try:
            document = marker.read_text(encoding="ascii", errors="replace")
        except OSError:
            document = ""
        boot = re.search(
            r"(?im)^\s*BOOT(2)?\s*=.*?([A-Z]{4})[_-](\d{3})[.]?(\d{2})",
            document,
        )
    if boot is None:
        # Scratched discs and a few ISO9660 drivers expose the boot executable
        # while SYSTEM.CNF is absent or unreadable. Its licensed serial still
        # identifies the disc deterministically.
        serial_marker = next(
            (path for path in volume_files if serial_pattern.match(path.name)),
            None,
        )
        if serial_marker is None:
            return None
        serial_match = serial_pattern.match(serial_marker.name)
        assert serial_match is not None
        groups = serial_match.groups()
        ps2_markers = ("IOPRP", "SIO2MAN", "CDVDMAN", "PS2LOGO")
        looks_ps2 = any(
            any(token in path.name.upper() for token in ps2_markers)
            for path in volume_files
        )
        platform = "playstation-2" if looks_ps2 else "playstation"
        serial = f"{groups[0].upper()}-{groups[1]}{groups[2]}"
    else:
        platform = "playstation-2" if boot.group(1) else "playstation"
        serial = f"{boot.group(2)}-{boot.group(3)}{boot.group(4)}"
    # SYSTEM.CNF is stored at the root of a PlayStation volume. Its direct
    # parent is therefore the mounted disc, unlike DVD-Video where the marker
    # sits one level lower inside VIDEO_TS.
    assert serial_marker is not None
    label = " ".join(volume.name.replace("_", " ").split()).strip()
    generic_labels = {"cdrom", "dvd", "disc", "disk", "media", "sr0"}
    serialish_label = re.fullmatch(r"[A-Z]{4}[-_. ]?\d{3}[.]?\d{2}", label, re.IGNORECASE)
    if not label or label.casefold() in generic_labels or serialish_label:
        label = "PlayStation 2 Game" if platform == "playstation-2" else "PlayStation Game"
    database_title = _playstation_disc_title(platform, serial)
    title = database_title or label
    device = next((path for path in ("/dev/sr0", "/dev/cdrom") if Path(path).exists()), "/dev/sr0")
    identity = hashlib.sha256(f"{platform}:{serial}".encode("ascii")).hexdigest()[:24]
    return {
        "content_id": identity,
        "title": title,
        "platform": platform,
        "runner": "pcsx2" if platform == "playstation-2" else "duckstation",
        "media_kind": "disc-image",
        "path": device,
        "source_root": str(volume),
        "read_only": True,
        "disc_serial": serial,
    }


def _optical_drive_media_present(device: Path = Path("/dev/sr0")) -> bool:
    """Check cached tray/media state without waking an empty optical drive."""
    try:
        details = device.stat()
        udev_state = Path(f"/run/udev/data/b{os.major(details.st_rdev)}:{os.minor(details.st_rdev)}")
        if udev_state.is_file():
            document = udev_state.read_text(encoding="utf-8", errors="replace")
            if "E:ID_CDROM_MEDIA=1" in document:
                return True
            # The udev record describes an optical drive but no inserted media.
            # Returning here avoids opening /dev/sr0 merely to illuminate its
            # activity LED once per UI refresh.
            if "E:ID_CDROM=1" in document:
                return False
    except OSError:
        pass
    # Compatibility fallback for minimal systems without a persistent udev
    # database.  It is still nonblocking, but normal PulseArc images use the
    # cached branch above.
    try:
        import fcntl

        descriptor = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
        try:
            # linux/cdrom.h: CDROM_DRIVE_STATUS, CDSL_CURRENT, CDS_DISC_OK.
            return int(fcntl.ioctl(descriptor, 0x5326, 0)) == 4
        finally:
            os.close(descriptor)
    except (ImportError, OSError, ValueError):
        return False


def _request_optical_mount() -> None:
    """Ask UDisks to mount a ready disc without blocking the 60 Hz shell."""
    try:
        subprocess.run(
            ["/usr/bin/udisksctl", "mount", "-b", "/dev/sr0"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _fast_optical_content_id(path: Path, platform: str) -> str:
    """Build a rename-stable ID while reading only a small ROM/executable sample."""
    digest = hashlib.sha256()
    try:
        size = path.stat().st_size
        digest.update(size.to_bytes(8, "little"))
        with path.open("rb") as handle:
            digest.update(handle.read(64 * 1024))
    except OSError:
        digest.update(path.name.casefold().encode("utf-8", errors="replace"))
    digest.update(platform.encode("utf-8", errors="replace"))
    return digest.hexdigest()[:24]


def _core_data_disc_modules() -> tuple[Any, Any, Any] | None:
    for path in reversed(PULSEARC_CORE_PATHS):
        value = str(path)
        if path.is_dir() and value not in sys.path:
            sys.path.insert(0, value)
    try:
        from pulsearc.legacy_kzi import load_legacy_kzi
        from pulsearc.manifest import load_manifest
        from pulsearc.media import detect
    except ImportError:
        return None
    return detect, load_manifest, load_legacy_kzi


def _manifest_data_disc_entry(volume: Path, manifest: Path) -> dict[str, Any] | None:
    modules = _core_data_disc_modules()
    if modules is None:
        return None
    detect, load_manifest, load_legacy_kzi = modules
    try:
        normalized_name = manifest.name.casefold().removesuffix(";1")
        if normalized_name.endswith(".kzi"):
            game = load_legacy_kzi(manifest)
            media_kind = game.media_kind
            cover = game.icon
        else:
            game = load_manifest(manifest)
            media_kind = "windows-program" if game.platform == "windows" else detect(game.entrypoint).media_kind
            cover = next(
                (candidate for candidate in (manifest.parent / "cover.png", manifest.parent / "icon.png")
                 if candidate.is_file()),
                None,
            )
        return {
            "content_id": _fast_optical_content_id(game.entrypoint, game.platform),
            "title": game.title,
            "platform": game.platform,
            "runner": game.runner,
            "media_kind": media_kind,
            "path": str(game.entrypoint),
            "source_root": str(manifest.parent),
            "read_only": True,
            "controller_profile": str(game.controller_profile) if game.controller_profile else "",
            "cover_path": str(cover) if cover else "",
            "serial": getattr(game, "serial", ""),
        }
    except (OSError, ValueError):
        return None


@functools.lru_cache(maxsize=64)
def _data_disc_entry_cached(volume_value: str, signature: tuple[tuple[str, int], ...]) -> dict[str, Any] | None:
    del signature  # It exists solely to invalidate the cache after media changes.
    volume = Path(volume_value)
    modules = _core_data_disc_modules()
    if modules is None:
        return None
    detect, _load_manifest, _load_legacy_kzi = modules

    manifests: list[Path] = []
    candidates: list[tuple[Path, Any]] = []
    try:
        roots = [volume] + sorted((item for item in volume.iterdir() if item.is_dir()), key=lambda item: item.name.casefold())
        for directory in roots:
            children = list(directory.iterdir())
            manifests.extend(
                path for path in children
                if path.is_file()
                and (
                    path.name.casefold().removesuffix(";1") == "pulsearc.toml"
                    or path.name.casefold().removesuffix(";1").endswith(".kzi")
                )
            )
            for path in children:
                if (
                    not path.is_file()
                    or path.name.casefold().removesuffix(";1") == "pulsearc.toml"
                    or path.name.casefold().removesuffix(";1").endswith(".kzi")
                ):
                    continue
                try:
                    result = detect(path)
                except (OSError, ValueError):
                    continue
                if result.media_kind in {"rom", "windows-program"}:
                    candidates.append((path, result))
    except OSError:
        return None

    if len(manifests) == 1:
        return _manifest_data_disc_entry(volume, manifests[0])
    if manifests or len(candidates) != 1:
        return None
    path, result = candidates[0]
    title = re.sub(r"\s*[\[(].*?[\])]\s*", " ", path.stem).replace("_", " ").strip() or path.stem
    cover = next((candidate for candidate in (path.parent / "cover.png", path.parent / "icon.png") if candidate.is_file()), None)
    return {
        "content_id": _fast_optical_content_id(path, result.platform),
        "title": " ".join(title.split()),
        "platform": result.platform,
        "runner": result.runner,
        "media_kind": result.media_kind,
        "path": str(path),
        "source_root": str(path.parent),
        "read_only": True,
        "cover_path": str(cover) if cover else "",
    }


def detected_data_disc(root: Path = REMOVABLE_ROOT) -> dict[str, Any] | None:
    """Expose one ROM or one portable PC package from a data CD/DVD as one game."""
    for volume in _optical_volumes(root):
        try:
            immediate = list(volume.iterdir())
        except OSError:
            continue
        names = {item.name.upper().removesuffix(";1") for item in immediate}
        if "SYSTEM.CNF" in names or "VIDEO_TS" in names:
            continue
        signature_items: list[tuple[str, int]] = []
        for item in immediate:
            try:
                signature_items.append((item.name, item.stat().st_size))
            except OSError:
                continue
        entry = _data_disc_entry_cached(str(volume.resolve()), tuple(sorted(signature_items)))
        if entry is not None:
            return entry
    return None


class ThemeVideo:
    """Decode a looping theme video off the UI thread at a modest resolution."""

    SIZE = (640, 360)

    def __init__(self, path: Path) -> None:
        self.path = path
        self.frame: bytes | None = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.process: subprocess.Popen[bytes] | None = None
        self.thread: threading.Thread | None = None
        self.pause_requested = False
        self.paused = False
        if shutil.which("ffmpeg"):
            self.thread = threading.Thread(target=self._decode, daemon=True, name="pulsearc-theme-video")
            self.thread.start()

    def _decode(self) -> None:
        width, height = self.SIZE
        command = [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-stream_loop", "-1",
            "-i", str(self.path), "-an", "-vf",
            f"fps=24,scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
        ]
        try:
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            if self.pause_requested:
                self._send_signal(getattr(signal, "SIGSTOP", None))
                self.paused = True
            frame_size = width * height * 3
            assert self.process.stdout is not None
            while not self.stop_event.is_set():
                chunks: list[bytes] = []
                remaining = frame_size
                while remaining and not self.stop_event.is_set():
                    chunk = self.process.stdout.read(remaining)
                    if not chunk:
                        return
                    chunks.append(chunk)
                    remaining -= len(chunk)
                if remaining == 0:
                    with self.lock:
                        self.frame = b"".join(chunks)
        except OSError:
            return
        finally:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()

    def surface(self) -> pygame.Surface | None:
        with self.lock:
            frame = self.frame
        if frame is None:
            return None
        try:
            return pygame.image.frombuffer(frame, self.SIZE, "RGB").copy()
        except (ValueError, pygame.error):
            return None

    def _send_signal(self, requested_signal: int | None) -> None:
        process = self.process
        if requested_signal is None or process is None or process.poll() is not None:
            return
        try:
            process.send_signal(requested_signal)
        except OSError:
            pass

    def pause(self) -> None:
        """Freeze decoding while retaining the last complete video frame."""
        self.pause_requested = True
        if not self.paused:
            self._send_signal(getattr(signal, "SIGSTOP", None))
            self.paused = self.process is not None and self.process.poll() is None

    def resume(self) -> None:
        """Resume video decoding after an external application closes."""
        self.pause_requested = False
        if self.paused:
            self._send_signal(getattr(signal, "SIGCONT", None))
            self.paused = False

    def close(self) -> None:
        self.stop_event.set()
        # A stopped ffmpeg process must be continued before terminate can be
        # delivered and reaped; otherwise changing themes can leave a zombie.
        self.pause_requested = False
        if self.paused:
            self._send_signal(getattr(signal, "SIGCONT", None))
            self.paused = False
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()


class PulseArcUI:
    def __init__(self, self_test: bool = False) -> None:
        pygame.init()
        pygame.font.init()
        pygame.joystick.init()
        pygame.mouse.set_visible(False)

        flags = 0 if self_test else pygame.FULLSCREEN | pygame.SCALED | pygame.DOUBLEBUF
        output_size = LOGICAL_SIZE if self_test else (0, 0)
        if not self_test:
            output_size = LOGICAL_SIZE
        self.screen = pygame.display.set_mode(output_size, flags, vsync=0 if self_test else 1)
        pygame.display.set_caption("PulseArc")
        self.canvas = self.screen
        self.clock = pygame.time.Clock()
        self.fonts = {
            "logo": pygame.font.SysFont("DejaVu Sans", 52, bold=True),
            "title": pygame.font.SysFont("DejaVu Sans", 34, bold=True),
            "menu": pygame.font.SysFont("DejaVu Sans", 25),
            "body": pygame.font.SysFont("DejaVu Sans", 20),
            "small": pygame.font.SysFont("DejaVu Sans", 15),
        }

        self.running = True
        self.exit_status = 0
        self.boot_started = time.monotonic()
        self.boot_duration = 0.0 if os.environ.get("PULSEARC_EXTERNAL_BOOT") == "1" else BOOT_SECONDS
        self.boot_finished = False
        self.start_screen_applied = False
        self.selection = 0
        self.screen_name = "profile-select"
        self.overlay_selection = 0
        self.cheat_content_id = ""
        self.cheat_system = ""
        self.library_system = ""
        self.cheat_games_cache: list[dict[str, Any]] = []
        self.cheat_entries_cache: list[dict[str, Any]] = []
        self.status = "A SELECT  •  B BACK  •  VIEW + MENU EXIT GAME"
        self.library: list[dict[str, Any]] = []
        self.covers: dict[str, str] = {}
        self.synopses: dict[str, str] = {}
        self.cover_images: dict[str, pygame.Surface | None] = {}
        self.last_library_read = 0.0
        self.last_ip_read = 0.0
        self.last_optical_mount_attempt = 0.0
        self.optical_media_reading = False
        # Physical optical reads must never run on the 60 Hz UI thread.  A
        # scratched CD can remain inside the kernel's retry path for many
        # seconds even when only the ISO9660 descriptor is requested.
        self.optical_media_was_present = False
        self.optical_probe_pending = False
        self.optical_cached_entry: dict[str, Any] | None = None
        self.optical_probe_generation = 0
        self.optical_probe_lock = threading.Lock()
        self.address = "pending network"
        self.controllers: dict[int, pygame.joystick.Joystick] = {}
        self.axis_latch = {"x": 0, "y": 0}
        self.axis_repeat_at = {"x": 0.0, "y": 0.0}
        self.view_down = False
        self.menu_down = False
        # Spawn just inside the glass entrance, facing the first stocked aisle.
        self.store_player = [10.0, 2.35]
        self.store_angle = math.pi / 2
        self.store_axes = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}
        self.store_focus_index: int | None = None
        self.store_detail_index: int | None = None
        self.store_case_angle = -0.16
        self.store_view = pygame.Surface((480, 270))
        self.power_items = ("SOFT RESTART FRONTEND", "RESTART COMPUTER", "SHUT DOWN")
        self.music_actions = ("INTERNET RADIO", "PLAY AUDIO CD", "SHUFFLE ALL MUSIC")
        self.tv_actions = ("FREE LIVE TV", "DVR RECORDINGS", "TV SOURCES", "BACK")
        self.apps_actions = (
            "STEAM BIG PICTURE",
            "EPIC + GOG LIBRARY (HEROIC)",
            "XBOX GAME PASS CLOUD GAMING",
            "GEFORCE NOW (NATIVE / WEB FALLBACK)",
            "PLAYSTATION PLUS CLOUD GAMING",
            "WEB BROWSER",
            "DOWNLOADS & EXTERNAL MEDIA",
            "BACK",
        )
        self.download_archives: list[ArchiveItem] = []
        self.tv_channels: list[dict[str, str]] = []
        self.tv_groups: list[tuple[str, int]] = []
        self.tv_group = ""
        self.tv_group_selection = 0
        self.tv_group_positions: dict[str, int] = {}
        self.tv_artwork_pending: set[str] = set()
        self.tv_active_source: dict[str, Any] | None = None
        self.tv_source_status = ""
        self.tv_epg_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self.tv_epg_pending: set[str] = set()
        self.dvr_process: subprocess.Popen[Any] | None = None
        self.dvr_title = ""
        self.dvr_partial_path: Path | None = None
        self.screen_record_process: subprocess.Popen[Any] | None = None
        self.screen_record_partial_path: Path | None = None
        self.wifi_entries: list[dict[str, Any]] = []
        self.wifi_target = ""
        self.wifi_password = ""
        self.bluetooth_entries: list[dict[str, Any]] = []
        self.profiles = load_profiles(PROFILES_PATH)
        try:
            requested_profile = ACTIVE_PROFILE_PATH.read_text(encoding="utf-8").strip().casefold()
        except OSError:
            requested_profile = "default"
        available_profiles = {profile["id"] for profile in self.profiles}
        self.profile_id = requested_profile if requested_profile in available_profiles else "default"
        self.profile_name = next(
            (profile["name"] for profile in self.profiles if profile["id"] == self.profile_id),
            "Default Profile",
        )
        self.overlay_selection = next(
            (index for index, profile in enumerate(self.profiles) if profile["id"] == self.profile_id),
            0,
        )
        self.profile_rename_id = ""
        self.profile_rename_text = ""
        self.profile_images: dict[str, pygame.Surface | None] = {}
        self.themes = discover_themes(BUILTIN_THEMES_PATH, USER_THEMES_PATH)
        self.theme: Theme | None = next(
            (theme for theme in self.themes if theme.theme_id == "pulsearc-classic"),
            self.themes[0] if self.themes else None,
        )
        self.theme_background: pygame.Surface | None = None
        self.theme_video: ThemeVideo | None = None
        self.theme_pause_depth = 0
        self.pending_profile_delete = ""
        self.install_thread: threading.Thread | None = None
        self.install_title = ""
        self.install_progress = 0.0
        self.install_bytes = 0
        self.install_total = 0
        self.install_started = 0.0
        self.install_phase = "IDLE"
        self.install_result = ""
        self.install_return_screen = "play"
        self.last_input_at = time.monotonic()
        self.screensaver_active = False
        self.screensaver_choices = (
            ("off", "OFF"),
            ("retro-grid", "RETRO GRID"),
            ("starfield", "NEON STARFIELD"),
            ("bouncing-orb", "BOUNCING PULSE ORB"),
        )
        self.extras_items = (
            "BIOS MANAGER",
            "PROFILES",
            "THEME MANAGEMENT",
            "SCREENSAVERS",
            "CONTROLLER REMAPPING",
            "ANTIMICROX PROFILES",
            "CHECK FOR UPDATES",
            "SCREEN RECORDING",
            "BLUETOOTH",
            "WI-FI",
            "BACK",
        )
        self.settings = self._load_settings()
        self._apply_theme(str(self.settings.get("theme", "pulsearc-classic")), persist=False)
        self._apply_master_volume()
        self.sounds = self._build_sounds()
        self.boot_sound_played = False
        self._open_existing_controllers()
        self._refresh_state(force=True)

    def _open_existing_controllers(self) -> None:
        for index in range(pygame.joystick.get_count()):
            joystick = pygame.joystick.Joystick(index)
            joystick.init()
            self.controllers[joystick.get_instance_id()] = joystick

    def _load_settings(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {
            "display_policy": "auto",
            "audio_policy": "hdmi",
            "master_volume": 100,
            "menu_sounds": True,
            "artwork_downloads": True,
            "start_screen": "home",
            "runtime_resolution": {"nintendo-64": "2x"},
            "theme": "pulsearc-classic",
            "screensaver": "retro-grid",
            "screensaver_idle": 30,
        }
        # The original global file is retained as the migration source for the
        # required Default Profile.  Other profiles own independent settings.
        sources = [SETTINGS_PATH] if self.profile_id == "default" else []
        sources.append(self._profile_settings_path())
        for source in sources:
            stored = read_json(source, {})
            if isinstance(stored, dict):
                defaults.update({key: stored[key] for key in defaults.keys() & stored.keys()})
        return defaults

    def _save_settings(self) -> None:
        try:
            destination = self._profile_settings_path()
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.settings, indent=2) + "\n", encoding="utf-8")
            temporary.replace(destination)
            if self.profile_id == "default":
                SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
                global_temporary = SETTINGS_PATH.with_suffix(".tmp")
                global_temporary.write_text(json.dumps(self.settings, indent=2) + "\n", encoding="utf-8")
                global_temporary.replace(SETTINGS_PATH)
        except OSError as exc:
            self.status = f"SETTINGS COULD NOT BE SAVED: {exc}"

    def _profile_settings_path(self) -> Path:
        return PROFILES_PATH.parent / self.profile_id / "settings.json"

    @staticmethod
    def _hex_color(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
        try:
            cleaned = value.strip().lstrip("#")
            if len(cleaned) != 6:
                return fallback
            return tuple(int(cleaned[index:index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
        except (TypeError, ValueError):
            return fallback

    def _apply_theme(self, theme_id: str, persist: bool = True) -> None:
        """Apply one validated theme, always falling back to PulseArc Classic."""
        global CYAN, PINK, WHITE, PURPLE, PANEL, MUTED, GREEN
        available = {theme.theme_id: theme for theme in self.themes}
        selected = available.get(theme_id) or available.get("pulsearc-classic")
        if selected is None:
            return
        self.theme = selected
        CYAN = self._hex_color(selected.accent, (80, 232, 255))
        PINK = self._hex_color(selected.secondary, (255, 85, 200))
        WHITE = self._hex_color(selected.text, (235, 241, 255))
        PURPLE = self._hex_color(selected.selection, CYAN)
        MUTED = self._hex_color(selected.muted, (172, 190, 230))
        GREEN = self._hex_color(selected.positive, (103, 217, 181))
        PANEL = (*self._hex_color(selected.panel, (10, 13, 31)), 225)
        if self.theme_video is not None:
            self.theme_video.close()
            self.theme_video = None
        self.theme_background = None
        image = selected.background
        if image is not None and image.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}:
            try:
                loaded = pygame.image.load(str(image)).convert()
                self.theme_background = pygame.transform.smoothscale(loaded, LOGICAL_SIZE)
            except (OSError, pygame.error):
                self.theme_background = None
        elif image is not None and image.suffix.casefold() in {".mp4", ".webm"}:
            self.theme_video = ThemeVideo(image)
            if self.theme_pause_depth:
                self.theme_video.pause()
            if selected.preview is not None:
                try:
                    loaded = pygame.image.load(str(selected.preview)).convert()
                    self.theme_background = pygame.transform.smoothscale(loaded, LOGICAL_SIZE)
                except (OSError, pygame.error):
                    self.theme_background = None
        elif selected.preview is not None:
            try:
                loaded = pygame.image.load(str(selected.preview)).convert()
                self.theme_background = pygame.transform.smoothscale(loaded, LOGICAL_SIZE)
            except (OSError, pygame.error):
                self.theme_background = None
        if selected.font is not None:
            try:
                self.fonts.update({
                    "logo": pygame.font.Font(str(selected.font), 52),
                    "title": pygame.font.Font(str(selected.font), 34),
                    "menu": pygame.font.Font(str(selected.font), 25),
                    "body": pygame.font.Font(str(selected.font), 20),
                    "small": pygame.font.Font(str(selected.font), 15),
                })
            except (OSError, pygame.error):
                pass
        if persist:
            self.settings["theme"] = selected.theme_id
            self._save_settings()
        self.cover_images.clear()

    def _pause_theme_animation(self) -> None:
        """Suspend animated theme work while a resource-heavy app owns focus."""
        self.theme_pause_depth += 1
        if self.theme_pause_depth == 1 and self.theme_video is not None:
            self.theme_video.pause()

    def _resume_theme_animation(self) -> None:
        """Resume the theme only after every nested heavy-app owner exits."""
        self.theme_pause_depth = max(0, self.theme_pause_depth - 1)
        if self.theme_pause_depth == 0 and self.theme_video is not None:
            self.theme_video.resume()

    def _activate_profile(self, profile_id: str) -> None:
        profile = next((item for item in self.profiles if item["id"] == profile_id), None)
        if profile is None:
            return
        self.profile_id = profile["id"]
        self.profile_name = profile["name"]
        ACTIVE_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = ACTIVE_PROFILE_PATH.with_suffix(".tmp")
        temporary.write_text(self.profile_id + "\n", encoding="utf-8")
        temporary.replace(ACTIVE_PROFILE_PATH)
        self.settings = self._load_settings()
        self._apply_theme(str(self.settings.get("theme", "pulsearc-classic")), persist=False)
        self._apply_master_volume()
        self.status = f"ACTIVE PROFILE: {self.profile_name.upper()}"

    def _profile_avatar_path(self, profile: dict[str, str] | None = None) -> Path | None:
        profile = profile or next((item for item in self.profiles if item["id"] == self.profile_id), None)
        if profile is None:
            return None
        icon = str(profile.get("icon") or "avatar-01")
        match = re.search(r"(\d{1,2})", icon)
        number = max(1, min(40, int(match.group(1)) if match else 1))
        path = PROFILE_AVATARS_PATH / f"avatar-{number:02d}.png"
        return path if path.is_file() else None

    def _profile_avatar(self, profile: dict[str, str] | None = None) -> pygame.Surface | None:
        path = self._profile_avatar_path(profile)
        key = str(path or "")
        if key not in self.profile_images:
            try:
                self.profile_images[key] = pygame.image.load(key).convert_alpha() if path else None
            except (OSError, pygame.error):
                self.profile_images[key] = None
        return self.profile_images[key]

    def _start_profile_rename(self, profile_id: str) -> None:
        profile = next((item for item in self.profiles if item["id"] == profile_id), None)
        if profile is None:
            return
        self.profile_rename_id = profile_id
        self.profile_rename_text = profile["name"]
        self._open("profile-rename")

    def _save_profile_rename(self) -> None:
        name = " ".join(self.profile_rename_text.split())[:28]
        profile = next((item for item in self.profiles if item["id"] == self.profile_rename_id), None)
        if profile is None or not name:
            self.status = "PROFILE NAME CANNOT BE EMPTY"
            return
        profile["name"] = name
        save_profiles(PROFILES_PATH, self.profiles)
        if profile["id"] == self.profile_id:
            self.profile_name = name
        self.status = f"PROFILE RENAMED: {name.upper()}"
        self.profile_rename_id = ""
        self.profile_rename_text = ""
        self._open("profiles")

    def _cycle_profile_avatar(self, amount: int) -> None:
        if not (0 <= self.overlay_selection < len(self.profiles)):
            return
        profile = self.profiles[self.overlay_selection]
        current = self._profile_avatar_path(profile)
        match = re.search(r"(\d{1,2})", current.stem if current else str(profile.get("icon", "1")))
        number = int(match.group(1)) if match else 1
        number = ((number - 1 + amount) % 40) + 1
        profile["icon"] = f"avatar-{number:02d}"
        try:
            save_profiles(PROFILES_PATH, self.profiles)
            self.status = f"PROFILE IMAGE {number:02d} SELECTED"
        except OSError as exc:
            self.status = f"PROFILE IMAGE COULD NOT BE SAVED: {exc}"

    def _add_profile(self) -> None:
        used = {item["id"] for item in self.profiles}
        profile_id = next((f"profile-{number}" for number in range(1, 4) if f"profile-{number}" not in used), "")
        if not profile_id:
            self.status = "THE FOUR-PROFILE LIMIT HAS BEEN REACHED"
            return
        number = profile_id.rsplit("-", 1)[-1]
        profile = {"id": profile_id, "name": f"Profile {number}", "icon": f"avatar-{int(number) + 1:02d}"}
        self.profiles.append(profile)
        try:
            save_profiles(PROFILES_PATH, self.profiles)
            self._activate_profile(profile_id)
            self.status = f"CREATED AND ACTIVATED {profile['name'].upper()}"
        except OSError as exc:
            self.profiles = [item for item in self.profiles if item["id"] != profile_id]
            self.status = f"PROFILE CREATE FAILED: {exc}"

    def _delete_pending_profile(self) -> None:
        profile_id = self.pending_profile_delete
        self.pending_profile_delete = ""
        if not profile_id or profile_id == "default":
            self.status = "THE DEFAULT PROFILE CANNOT BE DELETED"
            self._open("profiles")
            return
        profile = next((item for item in self.profiles if item["id"] == profile_id), None)
        if profile is None:
            self._open("profiles")
            return
        profile_root = PROFILES_PATH.parent / profile_id
        try:
            # Profile removal is recoverable: preserve saves/settings in an
            # archive instead of recursively deleting user data.
            if profile_root.exists():
                archive_root = PROFILES_PATH.parent / "archived"
                archive_root.mkdir(parents=True, exist_ok=True)
                archived = archive_root / f"{profile_id}-{int(time.time())}"
                profile_root.replace(archived)
            self.profiles = [item for item in self.profiles if item["id"] != profile_id]
            save_profiles(PROFILES_PATH, self.profiles)
            if self.profile_id == profile_id:
                self._activate_profile("default")
            self.status = f"REMOVED {profile['name'].upper()}; DATA ARCHIVED"
        except OSError as exc:
            self.status = f"PROFILE REMOVE FAILED: {exc}"
        self._open("profiles")

    def _import_theme_from_media(self) -> None:
        archives: list[Path] = []
        if REMOVABLE_ROOT.is_dir():
            for volume in sorted(REMOVABLE_ROOT.iterdir(), key=lambda item: item.name.casefold()):
                if not volume.is_dir() or volume.is_symlink():
                    continue
                for folder in (volume, volume / "PulseArc" / "Themes", volume / "Themes"):
                    if folder.is_dir() and not folder.is_symlink():
                        archives.extend(sorted(folder.glob("*.zip"), key=lambda item: item.name.casefold()))
        if not archives:
            self.status = "NO THEME ZIP FOUND IN USB/SD THEMES FOLDER"
            return
        errors: list[str] = []
        for archive in archives:
            try:
                theme_id = import_theme_archive(archive, USER_THEMES_PATH)
                self.themes = discover_themes(BUILTIN_THEMES_PATH, USER_THEMES_PATH)
                self._apply_theme(theme_id)
                self.overlay_selection = next(
                    (index for index, theme in enumerate(self.themes) if theme.theme_id == theme_id),
                    0,
                )
                self.status = f"IMPORTED AND APPLIED {archive.stem.upper()}"
                return
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                errors.append(str(exc))
        self.status = f"THEME IMPORT FAILED: {(errors[-1] if errors else 'INVALID ARCHIVE')[-120:]}"

    def _import_antimicrox_profiles(self) -> None:
        candidates: list[Path] = []
        if REMOVABLE_ROOT.is_dir():
            for volume in sorted(REMOVABLE_ROOT.iterdir(), key=lambda item: item.name.casefold()):
                if not volume.is_dir() or volume.is_symlink():
                    continue
                for folder in (volume / "PulseArc" / "Controllers", volume / "Controllers", volume):
                    if not folder.is_dir() or folder.is_symlink():
                        continue
                    for suffix in ("*.amgp", "*.xml"):
                        candidates.extend(sorted(folder.glob(suffix), key=lambda item: item.name.casefold()))
        destination = PROFILES_PATH.parent / self.profile_id / "controller-profiles" / "antimicrox"
        imported = 0
        try:
            destination.mkdir(parents=True, exist_ok=True)
            for source in candidates:
                if source.is_symlink() or not source.is_file() or source.stat().st_size > 2 * 1024 * 1024:
                    continue
                safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", source.name).strip(". ")
                if not safe_name:
                    continue
                temporary = destination / f".{safe_name}.tmp"
                shutil.copy2(source, temporary, follow_symlinks=False)
                temporary.replace(destination / safe_name)
                imported += 1
        except OSError as exc:
            self.status = f"ANTIMICROX IMPORT FAILED: {exc}"
            return
        self.status = (
            f"IMPORTED {imported} ANTIMICROX PROFILE{'S' if imported != 1 else ''}"
            if imported else "NO .AMGP OR .XML PROFILES FOUND ON USB/SD"
        )

    def _apply_master_volume(self) -> None:
        try:
            volume = max(0, min(100, int(self.settings.get("master_volume", 100))))
        except (TypeError, ValueError):
            volume = 100
        for command in (
            ["/usr/bin/wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
            ["/usr/bin/wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{volume / 100:.2f}"],
        ):
            subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _build_sounds(self) -> dict[str, pygame.mixer.Sound]:
        sounds: dict[str, pygame.mixer.Sound] = {}
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=512)
            for name, frequency, length in (
                ("move", 540, 0.045),
                ("accept", 820, 0.075),
                ("back", 330, 0.07),
                ("boot", 260, 0.65),
            ):
                samples = array("h")
                count = int(44100 * length)
                for index in range(count):
                    envelope = 1.0 - index / count
                    sweep = frequency + (index / max(1, count - 1)) * (600 if name == "boot" else 0)
                    samples.append(int(5000 * envelope * math.sin(2.0 * math.pi * sweep * index / 44100)))
                sounds[name] = pygame.mixer.Sound(buffer=samples.tobytes())
        except pygame.error:
            pass
        return sounds

    def _sound(self, name: str) -> None:
        if not self.settings.get("menu_sounds", True):
            return
        sound = self.sounds.get(name)
        if sound is not None:
            sound.play()

    def _start_optical_probe(self) -> None:
        """Probe newly inserted optical media without blocking the dashboard."""
        with self.optical_probe_lock:
            if self.optical_probe_pending:
                return
            self.optical_probe_pending = True
            self.optical_media_reading = True
            generation = self.optical_probe_generation
        threading.Thread(
            target=self._optical_probe_worker,
            args=(generation,),
            name="pulsearc-optical-probe",
            daemon=True,
        ).start()

    def _optical_probe_worker(self, generation: int) -> None:
        """Identify one disc once; removal invalidates an in-flight result."""
        entry: dict[str, Any] | None = None
        try:
            # PlayStation discs can be identified directly without a mount.
            entry = _direct_playstation_disc()
            if entry is None:
                # DVD-Video and loose-data discs need their mounted directory.
                _request_optical_mount()
                entry = detected_dvd_video() or detected_data_disc()
        except Exception:
            # Optical media is untrusted input.  A malformed filesystem or a
            # failing drive must degrade to an unreadable disc, not kill UI.
            entry = None
        finally:
            with self.optical_probe_lock:
                if generation == self.optical_probe_generation:
                    self.optical_cached_entry = entry
                    self.optical_media_reading = False
                self.optical_probe_pending = False

    def _refresh_state(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self.last_library_read >= 1.0:
            entries = read_json(LIBRARY_PATH, [])
            self.library = (
                [_normalize_ps3_entry(item) for item in entries if isinstance(item, dict)]
                if isinstance(entries, list)
                else []
            )
            # The system media daemon on early PulseArc images may index every
            # file inside an optical disc.  Hide those generic rows here so a
            # PS1/PS2/DVD contributes exactly one dedicated disc entry and can
            # never fill the normal or 3D library shelves with its contents.
            optical_roots = {
                str(volume.resolve())
                for volume in _optical_volumes(REMOVABLE_ROOT)
            }
            if optical_roots:
                self.library = [
                    item for item in self.library
                    if str(Path(str(item.get("source_root", ""))).resolve()) not in optical_roots
                ]
            media_present = _optical_drive_media_present()
            if not media_present:
                if self.optical_media_was_present or self.optical_cached_entry is not None:
                    with self.optical_probe_lock:
                        self.optical_probe_generation += 1
                        self.optical_cached_entry = None
                        self.optical_media_reading = False
                    OPTICAL_ENTRY_PATH.unlink(missing_ok=True)
            elif not self.optical_media_was_present:
                self._start_optical_probe()
            self.optical_media_was_present = media_present
            with self.optical_probe_lock:
                active_optical_entry = self.optical_cached_entry
            playstation_entry = (
                active_optical_entry
                if active_optical_entry is not None
                and str(active_optical_entry.get("platform", "")) in {"playstation", "playstation-2"}
                else None
            )
            dvd_entry = (
                active_optical_entry
                if active_optical_entry is not None
                and str(active_optical_entry.get("platform", "")) == "dvd-video"
                else None
            )
            data_disc_entry = (
                active_optical_entry
                if active_optical_entry is not None
                and playstation_entry is None
                and dvd_entry is None
                else None
            )
            try:
                if active_optical_entry is not None:
                    temporary_optical = OPTICAL_ENTRY_PATH.with_suffix(".json.tmp")
                    temporary_optical.write_text(json.dumps(active_optical_entry, indent=2), encoding="utf-8")
                    temporary_optical.replace(OPTICAL_ENTRY_PATH)
                elif not self.optical_media_reading:
                    OPTICAL_ENTRY_PATH.unlink(missing_ok=True)
            except OSError:
                pass
            if playstation_entry is not None:
                disc_root = str(playstation_entry.get("source_root", ""))
                self.library = [item for item in self.library if str(item.get("source_root", "")) != disc_root]
                self.library.insert(0, playstation_entry)
            elif dvd_entry is not None:
                dvd_root = str(dvd_entry.get("source_root", ""))
                self.library = [item for item in self.library if str(item.get("source_root", "")) != dvd_root]
                self.library.insert(0, dvd_entry)
            elif data_disc_entry is not None:
                disc_root = str(data_disc_entry.get("source_root", ""))
                self.library = [item for item in self.library if str(item.get("source_root", "")) != disc_root]
                self.library.insert(0, data_disc_entry)
            cover_values = read_json(COVERS_PATH, {})
            self.covers = cover_values if isinstance(cover_values, dict) else {}
            synopsis_values = read_json(SYNOPSES_PATH, {})
            self.synopses = synopsis_values if isinstance(synopsis_values, dict) else {}
            self.last_library_read = now
        if force or now - self.last_ip_read >= 3.0:
            self.address = local_ipv4()
            self.last_ip_read = now

    def run(self) -> int:
        while self.running:
            self._refresh_state()
            self._events()
            if not self.boot_sound_played and time.monotonic() - self.boot_started >= 0.8:
                self._apply_master_volume()
                self._sound("boot")
                self.boot_sound_played = True
            if time.monotonic() - self.boot_started >= self.boot_duration:
                self.boot_finished = True
            try:
                idle_seconds = max(10, int(self.settings.get("screensaver_idle", 30)))
            except (TypeError, ValueError):
                idle_seconds = 30
            if (
                self.boot_finished
                and self.screen_name == "home"
                and str(self.settings.get("screensaver", "retro-grid")) != "off"
                and time.monotonic() - self.last_input_at >= idle_seconds
            ):
                self.screensaver_active = True
            self._update_3d_store(min(0.05, self.clock.get_time() / 1000.0))
            self._draw()
            pygame.display.flip()
            self.clock.tick(60)
        self._stop_screen_recording(silent=True)
        self._stop_dvr_recording(silent=True)
        if self.theme_video is not None:
            self.theme_video.close()
        pygame.quit()
        return self.exit_status

    def _check_or_apply_update(self) -> None:
        pending = str(getattr(self, "pending_update_version", ""))
        try:
            if pending:
                result = subprocess.run(
                    ["/usr/bin/sudo", "-n", "/usr/local/sbin/pulsearc-update", "--apply"],
                    check=False, capture_output=True, text=True, timeout=180.0,
                )
                payload = json.loads((result.stdout or "{}").strip().splitlines()[-1])
                if result.returncode != 0 or payload.get("error"):
                    self.status = f"UPDATE FAILED AND ROLLED BACK: {payload.get('error', result.stderr)[-100:]}"
                    self.pending_update_version = ""
                    return
                self.pending_update_version = ""
                self.exit_status = 75
                self.running = False
                return
            result = subprocess.run(
                ["/usr/local/sbin/pulsearc-update", "--check"],
                check=False, capture_output=True, text=True, timeout=15.0,
            )
            payload = json.loads((result.stdout or "{}").strip().splitlines()[-1])
            if result.returncode != 0 or payload.get("error"):
                self.status = f"UPDATE CHECK FAILED: {payload.get('error', result.stderr)[-110:]}"
            elif payload.get("available"):
                self.pending_update_version = str(payload.get("version", "UPDATE"))
                self.status = f"{self.pending_update_version.upper()} AVAILABLE  •  PRESS A AGAIN TO INSTALL"
            else:
                self.status = f"PULSEARC {str(payload.get('current_version', 'CURRENT')).upper()} IS UP TO DATE"
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, IndexError) as exc:
            self.status = f"UPDATE CHECK FAILED: {str(exc)[-110:]}"

    def _events(self) -> None:
        for event in pygame.event.get():
            if event.type in {
                pygame.KEYDOWN,
                pygame.JOYBUTTONDOWN,
                pygame.JOYHATMOTION,
                pygame.JOYAXISMOTION,
            }:
                # The first input only wakes the dashboard; it must not also
                # launch or move a menu item hidden behind the screensaver.
                meaningful_axis = event.type != pygame.JOYAXISMOTION or abs(float(event.value)) > 0.55
                meaningful_hat = event.type != pygame.JOYHATMOTION or event.value != (0, 0)
                if meaningful_axis and meaningful_hat:
                    self.last_input_at = time.monotonic()
                    if self.screensaver_active:
                        self.screensaver_active = False
                        continue
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.JOYDEVICEADDED:
                stick = pygame.joystick.Joystick(event.device_index)
                stick.init()
                self.controllers[stick.get_instance_id()] = stick
            elif event.type == pygame.JOYDEVICEREMOVED:
                self.controllers.pop(event.instance_id, None)
            elif event.type == pygame.KEYDOWN:
                if self.screen_name in ("wifi-password", "profile-rename"):
                    if event.key == pygame.K_ESCAPE:
                        self._open("wifi" if self.screen_name == "wifi-password" else "profiles")
                    elif event.key == pygame.K_BACKSPACE:
                        if self.screen_name == "wifi-password":
                            self.wifi_password = self.wifi_password[:-1]
                        else:
                            self.profile_rename_text = self.profile_rename_text[:-1]
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if self.screen_name == "wifi-password":
                            self._connect_wifi_password()
                        else:
                            self._save_profile_rename()
                    elif event.unicode and event.unicode.isprintable():
                        if self.screen_name == "wifi-password":
                            self.wifi_password = (self.wifi_password + event.unicode)[:128]
                        else:
                            self.profile_rename_text = (self.profile_rename_text + event.unicode)[:28]
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    self._accept()
                elif event.key == pygame.K_ESCAPE:
                    self._back()
                elif event.key in (pygame.K_UP, pygame.K_w):
                    self._move(-1)
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    self._move(1)
                elif event.key in (pygame.K_LEFT, pygame.K_a):
                    self._move_horizontal(-1)
                elif event.key in (pygame.K_RIGHT, pygame.K_d):
                    self._move_horizontal(1)
            elif event.type == pygame.JOYHATMOTION:
                if event.value[0]:
                    self._move_horizontal(event.value[0])
                if event.value[1] > 0:
                    self._move(-1)
                elif event.value[1] < 0:
                    self._move(1)
            elif event.type == pygame.JOYAXISMOTION and event.axis in (0, 1, 2, 3):
                if self.screen_name == "3d-library":
                    self.store_axes[event.axis] = float(event.value)
                elif self.screen_name == "3d-details" and event.axis == 2:
                    self.store_axes[event.axis] = float(event.value)
                else:
                    if event.axis in (0, 1):
                        self._axis(event.axis, float(event.value))
            elif event.type == pygame.JOYBUTTONDOWN:
                self._button(event.button, True)
            elif event.type == pygame.JOYBUTTONUP:
                self._button(event.button, False)

    def _axis(self, axis: int, value: float) -> None:
        key = "x" if axis == 0 else "y"
        direction = 0 if abs(value) < 0.55 else (1 if value > 0 else -1)
        now = time.monotonic()
        if direction == 0:
            self.axis_latch[key] = 0
            return
        if self.axis_latch[key] != direction or now >= self.axis_repeat_at[key]:
            if key == "y":
                self._move(direction)
            else:
                self._move_horizontal(direction)
            self.axis_latch[key] = direction
            self.axis_repeat_at[key] = now + 0.24

    def _button(self, button: int, pressed: bool) -> None:
        # SDL's standard Xbox order: South/A=0, East/B=1, View=6, Menu=7.
        if button == 6:
            self.view_down = pressed
        elif button == 7:
            self.menu_down = pressed
        if pressed and self.view_down and self.menu_down:
            self.status = "EXIT HOTKEY READY"
            return
        if not pressed:
            return
        if button == 0:
            self._accept()
        elif button == 1:
            self._back()
        elif button == 2 and self.screen_name == "home" and MENU[self.selection][0] == "PLAY":
            entries = self._entries_for_screen()
            if len(entries) == 1:
                self._start_install(entries[0])
            elif entries:
                self.status = "CHOOSE THE GAME OR DISC TO INSTALL"
                self._open("play")
            else:
                self.status = "NO EXTERNAL GAME OR DISC IS READY TO INSTALL"
        elif button == 2 and self.screen_name == "play":
            entries = self._entries_for_screen()
            if self.overlay_selection < len(entries):
                self._start_install(entries[self.overlay_selection])
        elif button == 2 and self.screen_name == "profiles":
            if self.overlay_selection < len(self.profiles):
                profile_id = self.profiles[self.overlay_selection]["id"]
                if profile_id == "default":
                    self.status = "THE DEFAULT PROFILE CANNOT BE DELETED"
                else:
                    self.pending_profile_delete = profile_id
                    self._open("profile-delete-confirm")
        elif button == 3 and self.screen_name == "profiles" and self.overlay_selection < len(self.profiles):
            self._start_profile_rename(self.profiles[self.overlay_selection]["id"])
        elif button == 4 and self.screen_name == "profiles":
            self._cycle_profile_avatar(-1)
        elif button == 5 and self.screen_name == "profiles":
            self._cycle_profile_avatar(1)
        elif button == 2 and self.screen_name == "tv-sources":
            self._delete_selected_tv_source()
        elif button == 5 and self.screen_name == "tv-channels":
            self._toggle_selected_dvr_recording()
        elif button == 2 and self.screen_name == "dvr":
            self._delete_selected_dvr_recording()
        elif button == 2 and self.screen_name == "wifi":
            self._refresh_wifi()
        elif button == 2 and self.screen_name == "bluetooth":
            self._refresh_bluetooth()
        elif button == 2 and self.screen_name == "wifi-password":
            self.wifi_password = self.wifi_password[:-1]
        elif button == 5 and self.screen_name == "bluetooth":
            self._disconnect_selected_bluetooth()

    def _count(self) -> int:
        if self.screen_name == "home":
            return len(MENU)
        if self.screen_name == "profile-select":
            return max(1, len(self.profiles))
        if self.screen_name == "play":
            return max(2, len(self._entries_for_screen()) + 2)
        if self.screen_name == "install-progress":
            return 1
        if self.screen_name == "library":
            return max(1, len(self._library_systems()) + 1)
        if self.screen_name == "library-games":
            return max(1, len(self._library_games_for_system()) + 1)
        if self.screen_name == "power":
            return len(self.power_items) + 1
        if self.screen_name == "music":
            return len(self.music_actions) + len(self._music_entries()) + 1
        if self.screen_name == "radio":
            return len(RADIO_STATIONS) + 1
        if self.screen_name == "tv":
            return len(self.tv_actions)
        if self.screen_name == "apps":
            return len(self.apps_actions)
        if self.screen_name == "downloads":
            return max(1, len(self.download_archives) + 2)
        if self.screen_name == "dvr":
            return max(1, len(self._dvr_recordings()) + 1)
        if self.screen_name == "tv-groups":
            return max(1, len(self.tv_groups) + 1)
        if self.screen_name == "tv-channels":
            return max(1, len(self._tv_channels_for_group()) + 1)
        if self.screen_name == "tv-apps":
            return len(FREE_STREAMING_APPS) + 1
        if self.screen_name == "tv-sources":
            return len(self._tv_sources()) + 3
        if self.screen_name == "wifi":
            return len(self.wifi_entries) + 2
        if self.screen_name == "wifi-password":
            return len(ONSCREEN_KEYS)
        if self.screen_name == "bluetooth":
            return len(self.bluetooth_entries) + 2
        if self.screen_name == "settings":
            return 9
        if self.screen_name == "runtime-settings":
            return 2
        if self.screen_name == "extras":
            return len(self.extras_items)
        if self.screen_name == "profiles":
            return len(self.profiles) + (1 if len(self.profiles) < MAX_PROFILES else 0) + 1
        if self.screen_name == "profile-delete-confirm":
            return 2
        if self.screen_name == "profile-rename":
            return len(PROFILE_KEYS)
        if self.screen_name == "themes":
            return len(self.themes) + 2
        if self.screen_name == "screensavers":
            return len(self.screensaver_choices) + 1
        if self.screen_name in ("controller-remapping", "antimicrox"):
            return 2
        if self.screen_name == "bios":
            return len(BIOS_REQUIREMENTS) + 1
        if self.screen_name == "cheats":
            return max(1, len(self._cheat_systems()) + 1)
        if self.screen_name == "cheat-games":
            return max(1, len(self._cheat_games_for_system()) + 1)
        if self.screen_name == "cheat-details":
            return max(1, len(self._cheat_entries()) + 1)
        if self.screen_name in ("3d-library", "3d-details"):
            return 1
        return 1

    def _move(self, amount: int) -> None:
        if not self.boot_finished:
            return
        if self.screen_name == "3d-library":
            self._store_step(-amount * 0.42)
            self._sound("move")
            return
        if self.screen_name in ("wifi-password", "profile-rename"):
            keys = ONSCREEN_KEYS if self.screen_name == "wifi-password" else PROFILE_KEYS
            self.overlay_selection = max(
                0,
                min(len(keys) - 1, self.overlay_selection + amount * ONSCREEN_COLUMNS),
            )
            self._sound("move")
            return
        if self.screen_name in ("library", "library-games", "cheats", "cheat-games", "cheat-details", "downloads") or (
            self.screen_name == "tv-channels" and self.tv_group.startswith("VOD / ")
        ):
            columns = 1 if self.screen_name == "downloads" else 2 if self.screen_name == "cheat-details" else 4
            item_count = self._count() - 1
            if self.overlay_selection >= item_count:
                self.overlay_selection = max(0, item_count - 1) if amount < 0 else 0
            else:
                target = self.overlay_selection + amount * columns
                self.overlay_selection = item_count if target >= item_count else max(0, target)
            self._sound("move")
            return
        self.overlay_selection = (self.overlay_selection + amount) % self._count()
        if self.screen_name == "home":
            self.selection = self.overlay_selection
        self._sound("move")

    def _move_horizontal(self, amount: int) -> None:
        if self.screen_name in ("profile-select", "profiles"):
            self.overlay_selection = (self.overlay_selection + amount) % self._count()
            self._sound("move")
        elif self.screen_name == "3d-library":
            if not self._store_cycle_case(amount):
                self.store_angle = (self.store_angle + amount * 0.22) % math.tau
            self._sound("move")
        elif self.screen_name == "3d-details":
            self.store_case_angle = (self.store_case_angle + amount * 0.20) % math.tau
            self._sound("move")
        elif self.screen_name in ("library", "library-games", "cheats", "cheat-games", "cheat-details") or (
            self.screen_name == "tv-channels" and self.tv_group.startswith("VOD / ")
        ):
            self.overlay_selection = (self.overlay_selection + amount) % self._count()
            self._sound("move")
        elif self.screen_name in ("wifi-password", "profile-rename"):
            keys = ONSCREEN_KEYS if self.screen_name == "wifi-password" else PROFILE_KEYS
            self.overlay_selection = (self.overlay_selection + amount) % len(keys)
            self._sound("move")

    def _accept(self) -> None:
        if not self.boot_finished:
            return
        self._sound("accept")
        if self.screen_name == "profile-select":
            if self.profiles:
                self._activate_profile(self.profiles[self.overlay_selection]["id"])
            self.start_screen_applied = True
            self._open("home")
            if self.settings.get("start_screen") == "3d-library":
                self._launch_3d_library()
        elif self.screen_name == "home":
            item = MENU[self.selection][0]
            external_entries = self._entries_for_screen()
            if item == "PLAY" and not external_entries:
                self.status = "INSERT USB, SD, CD, DVD, OR A LEGACY KZI CARTRIDGE"
            elif item == "PLAY" and len(external_entries) == 1:
                # A single detected cart/media item behaves like a console:
                # Play launches it immediately without an unnecessary picker.
                self._launch(external_entries[0])
            elif item == "PLAY":
                self._open("play")
            elif item == "LIBRARY":
                self._open("library")
            elif item == "3D PLAZA":
                self._launch_3d_library()
            elif item == "MUSIC":
                self._open("music")
            elif item == "TV":
                self._open("tv")
            elif item == "APPS":
                self._open("apps")
            elif item == "SAVES":
                self._open("saves")
            elif item == "CHEATS":
                self._open("cheats")
            elif item == "CONTROLLERS":
                self._open("controllers")
            elif item == "SETTINGS":
                self._open("settings")
            elif item == "EXTRAS":
                self._open("extras")
            elif item == "POWER":
                self._open("power")
        elif self.screen_name == "play":
            entries = self._entries_for_screen()
            if self.overlay_selection == len(entries):
                self._install_all_external_games()
            elif self.overlay_selection > len(entries):
                self._back()
            elif entries:
                self._launch(entries[self.overlay_selection])
        elif self.screen_name == "install-progress":
            if self.install_result:
                self._refresh_state(force=True)
                self._open(self.install_return_screen)
        elif self.screen_name == "library":
            systems = self._library_systems()
            if self.overlay_selection >= len(systems):
                self._back()
            elif systems:
                self.library_system = systems[self.overlay_selection][0]
                self._open("library-games")
        elif self.screen_name == "library-games":
            entries = self._library_games_for_system()
            if self.overlay_selection >= len(entries):
                self._open("library")
            elif entries:
                self._launch(entries[self.overlay_selection], return_screen="library-games")
        elif self.screen_name == "3d-library":
            if self.store_focus_index is None:
                self.status = "MOVE CLOSER AND FACE A CASE TO SELECT IT"
            else:
                self.store_detail_index = self.store_focus_index
                self._open("3d-details")
        elif self.screen_name == "3d-details":
            entries = self._store_entries()
            if self.store_detail_index is not None and self.store_detail_index < len(entries):
                self._launch(entries[self.store_detail_index], return_screen="3d-library")
        elif self.screen_name == "power":
            if self.overlay_selection == len(self.power_items):
                self._back()
            else:
                self._power(self.overlay_selection)
        elif self.screen_name == "music":
            if self.overlay_selection == 0:
                self._open("radio")
            elif self.overlay_selection == 1:
                self._play_audio_cd()
            elif self.overlay_selection == 2:
                self._play_detected_music()
            elif self.overlay_selection < len(self.music_actions) + len(self._music_entries()):
                music = self._music_entries()[self.overlay_selection - len(self.music_actions)]
                self._play_music_entry(music)
            else:
                self._back()
        elif self.screen_name == "radio":
            if self.overlay_selection >= len(RADIO_STATIONS):
                self._open("music")
            else:
                self._play_radio_station(RADIO_STATIONS[self.overlay_selection])
        elif self.screen_name == "tv":
            if self.overlay_selection == 0:
                self._refresh_tv_channels(dict(BUILTIN_TV_SOURCES[0]))
            elif self.overlay_selection == 1:
                self._open("dvr")
            elif self.overlay_selection == 2:
                self._open("tv-sources")
            else:
                self._back()
        elif self.screen_name == "apps":
            self._apps_action(self.overlay_selection)
        elif self.screen_name == "downloads":
            if self.overlay_selection < len(self.download_archives):
                self._start_archive_install(self.download_archives[self.overlay_selection])
            elif self.overlay_selection == len(self.download_archives):
                self._refresh_download_archives()
            else:
                self._open("apps")
        elif self.screen_name == "tv-groups":
            if self.overlay_selection >= len(self.tv_groups):
                self._open("tv")
            elif self.tv_groups:
                self.tv_group_selection = self.overlay_selection
                self.tv_group = self.tv_groups[self.overlay_selection][0]
                self._open("tv-channels")
                self.overlay_selection = min(
                    self.tv_group_positions.get(self.tv_group, 0),
                    max(0, len(self._tv_channels_for_group()) - 1),
                )
        elif self.screen_name == "tv-channels":
            channels = self._tv_channels_for_group()
            if self.overlay_selection >= len(channels):
                self._return_to_tv_groups()
            elif channels:
                self._play_tv_channel(channels[self.overlay_selection])
        elif self.screen_name == "dvr":
            recordings = self._dvr_recordings()
            if self.overlay_selection >= len(recordings):
                self._open("tv")
            elif recordings:
                self._play_dvr_recording(recordings[self.overlay_selection])
        elif self.screen_name == "tv-apps":
            if self.overlay_selection >= len(FREE_STREAMING_APPS):
                self._open("tv")
            else:
                self._launch_streaming_app(FREE_STREAMING_APPS[self.overlay_selection])
        elif self.screen_name == "tv-sources":
            sources = self._tv_sources()
            if self.overlay_selection < len(sources):
                self._refresh_tv_channels(sources[self.overlay_selection])
            elif self.overlay_selection == len(sources):
                self._import_tv_sources()
            elif self.overlay_selection == len(sources) + 1:
                self._refresh_tv_channels()
            else:
                self._open("tv")
        elif self.screen_name == "settings":
            self._settings_action(self.overlay_selection)
        elif self.screen_name == "runtime-settings":
            self._runtime_settings_action(self.overlay_selection)
        elif self.screen_name == "extras":
            item = self.extras_items[self.overlay_selection]
            if item == "BIOS MANAGER":
                self._open("bios")
            elif item == "PROFILES":
                self._open("profiles")
            elif item == "THEME MANAGEMENT":
                self._open("themes")
            elif item == "SCREENSAVERS":
                self._open("screensavers")
            elif item == "CONTROLLER REMAPPING":
                self._open("controller-remapping")
            elif item == "ANTIMICROX PROFILES":
                self._open("antimicrox")
            elif item == "CHECK FOR UPDATES":
                self._check_or_apply_update()
            elif item == "SCREEN RECORDING":
                self._toggle_screen_recording()
            elif item == "BLUETOOTH":
                self._open("bluetooth")
            elif item == "WI-FI":
                self._open("wifi")
            else:
                self._back()
        elif self.screen_name == "profiles":
            if self.overlay_selection < len(self.profiles):
                self._activate_profile(self.profiles[self.overlay_selection]["id"])
            elif len(self.profiles) < MAX_PROFILES and self.overlay_selection == len(self.profiles):
                self._add_profile()
            else:
                self._open("extras")
        elif self.screen_name == "profile-delete-confirm":
            if self.overlay_selection == 0:
                self._delete_pending_profile()
            else:
                self.pending_profile_delete = ""
                self._open("profiles")
        elif self.screen_name == "profile-rename":
            key = PROFILE_KEYS[self.overlay_selection]
            if key == "BACKSPACE":
                self.profile_rename_text = self.profile_rename_text[:-1]
            elif key == "SAVE":
                self._save_profile_rename()
            elif key == "CANCEL":
                self.profile_rename_id = ""
                self.profile_rename_text = ""
                self._open("profiles")
            else:
                self.profile_rename_text = (self.profile_rename_text + key)[:28]
        elif self.screen_name == "themes":
            if self.overlay_selection < len(self.themes):
                self._apply_theme(self.themes[self.overlay_selection].theme_id)
                self.status = f"THEME APPLIED: {self.themes[self.overlay_selection].name.upper()}"
            elif self.overlay_selection == len(self.themes):
                self._import_theme_from_media()
            else:
                self._open("extras")
        elif self.screen_name == "screensavers":
            if self.overlay_selection < len(self.screensaver_choices):
                saver_id, saver_name = self.screensaver_choices[self.overlay_selection]
                self.settings["screensaver"] = saver_id
                self._save_settings()
                self.status = f"SCREENSAVER: {saver_name}"
            else:
                self._open("extras")
        elif self.screen_name == "controller-remapping":
            if self.overlay_selection == 0:
                self._open("controllers")
            else:
                self._open("extras")
        elif self.screen_name == "antimicrox":
            if self.overlay_selection == 0:
                self._import_antimicrox_profiles()
            else:
                self._open("extras")
        elif self.screen_name == "wifi":
            if self.overlay_selection < len(self.wifi_entries):
                self._select_wifi(self.wifi_entries[self.overlay_selection])
            elif self.overlay_selection == len(self.wifi_entries):
                self._refresh_wifi()
            else:
                self._open("extras")
        elif self.screen_name == "wifi-password":
            key = ONSCREEN_KEYS[self.overlay_selection]
            if key == "BACKSPACE":
                self.wifi_password = self.wifi_password[:-1]
            elif key == "CONNECT":
                self._connect_wifi_password()
            elif key == "CANCEL":
                self.wifi_password = ""
                self._open("wifi")
            else:
                self.wifi_password = (self.wifi_password + key)[:128]
        elif self.screen_name == "bluetooth":
            if self.overlay_selection < len(self.bluetooth_entries):
                self._select_bluetooth(self.bluetooth_entries[self.overlay_selection])
            elif self.overlay_selection == len(self.bluetooth_entries):
                self._refresh_bluetooth()
            else:
                self._open("extras")
        elif self.screen_name == "bios":
            if self.overlay_selection >= len(BIOS_REQUIREMENTS):
                self._open("extras")
            else:
                self._import_bios(BIOS_REQUIREMENTS[self.overlay_selection])
        elif self.screen_name == "cheats":
            systems = self._cheat_systems()
            if self.overlay_selection >= len(systems):
                self._back()
            elif systems:
                self.cheat_system = str(systems[self.overlay_selection][0])
                self._open("cheat-games")
        elif self.screen_name == "cheat-games":
            games = self._cheat_games_for_system()
            if self.overlay_selection >= len(games):
                self._open("cheats")
            elif games:
                self.cheat_content_id = str(games[self.overlay_selection].get("content_id", ""))
                self._open("cheat-details")
        elif self.screen_name == "cheat-details":
            cheats = self._cheat_entries()
            if self.overlay_selection >= len(cheats):
                self._open("cheats")
            elif cheats:
                self._toggle_selected_cheat(self.overlay_selection)
        else:
            self._back()

    def _back(self) -> None:
        if not self.boot_finished:
            return
        self._sound("back")
        if self.screen_name == "home":
            self.status = "BACK"
            return
        if self.screen_name == "profile-select":
            return
        if self.screen_name == "3d-details":
            self._launch_3d_library()
            return
        if self.screen_name == "install-progress":
            if self.install_result:
                self._refresh_state(force=True)
                self._open(self.install_return_screen)
            return
        if self.screen_name == "cheat-details":
            self._open("cheat-games")
            return
        if self.screen_name == "cheat-games":
            self._open("cheats")
            return
        if self.screen_name == "library-games":
            self._open("library")
            return
        if self.screen_name == "profile-delete-confirm":
            self.pending_profile_delete = ""
            self._open("profiles")
            return
        if self.screen_name == "profile-rename":
            self.profile_rename_id = ""
            self.profile_rename_text = ""
            self._open("profiles")
            return
        if self.screen_name in ("profiles", "themes", "screensavers", "controller-remapping", "antimicrox"):
            self._open("extras")
            return
        if self.screen_name == "bios":
            self._open("extras")
            return
        if self.screen_name == "wifi-password":
            self.wifi_password = ""
            self._open("wifi")
            return
        if self.screen_name in ("wifi", "bluetooth"):
            self._open("extras")
            return
        if self.screen_name == "radio":
            self._open("music")
            return
        if self.screen_name == "downloads":
            self._open("apps")
            return
        if self.screen_name in ("tv-groups", "tv-apps", "tv-sources", "dvr"):
            self._open("tv")
            return
        if self.screen_name == "tv-channels":
            self._return_to_tv_groups()
            return
        self.screen_name = "home"
        self.overlay_selection = self.selection

    def _open(self, name: str) -> None:
        self.screen_name = name
        self.overlay_selection = 0
        if name == "cheats":
            self.cheat_games_cache = self._query_cheat_games()
        elif name == "cheat-details":
            self.cheat_entries_cache = self._query_cheat_entries()
        elif name == "wifi":
            self._refresh_wifi()
        elif name == "bluetooth":
            self._refresh_bluetooth()
        elif name == "downloads":
            self._refresh_download_archives()
        if name != "3d-library":
            self.store_axes = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}

    def _return_to_tv_groups(self) -> None:
        self.tv_group_positions[self.tv_group] = self.overlay_selection
        self._open("tv-groups")
        self.overlay_selection = min(self.tv_group_selection, max(0, len(self.tv_groups) - 1))

    def _refresh_wifi(self) -> None:
        self.status = "SCANNING FOR WI-FI NETWORKS"
        self.wifi_entries = wifi_networks(rescan=True)
        self.overlay_selection = 0
        self.status = (
            f"FOUND {len(self.wifi_entries)} WI-FI NETWORKS"
            if self.wifi_entries else "NO WI-FI NETWORKS FOUND; CHECK THE ADAPTER"
        )

    def _select_wifi(self, network: dict[str, Any]) -> None:
        ssid = str(network.get("ssid", "")).strip()
        if not ssid:
            return
        if bool(network.get("active")):
            self.status = f"{ssid} IS ALREADY CONNECTED"
            return
        security = str(network.get("security", "OPEN")).upper()
        self.status = f"CONNECTING TO {ssid}"
        success, message = connect_wifi(ssid)
        if success:
            self.status = f"CONNECTED TO {ssid}"
            self._refresh_wifi()
            return
        if security in {"", "--", "OPEN"}:
            self.status = f"WI-FI CONNECTION FAILED: {message[-80:]}"
            return
        self.wifi_target = ssid
        self.wifi_password = ""
        self._open("wifi-password")
        self.status = f"ENTER PASSWORD FOR {ssid}"

    def _connect_wifi_password(self) -> None:
        if not self.wifi_target:
            self._open("wifi")
            return
        ssid = self.wifi_target
        password = self.wifi_password
        self.status = f"CONNECTING TO {ssid}"
        success, message = connect_wifi(ssid, password)
        self.wifi_password = ""
        if success:
            self.status = f"CONNECTED TO {ssid}"
            self._open("wifi")
        else:
            self.status = f"WI-FI CONNECTION FAILED: {message[-80:]}"

    def _refresh_bluetooth(self) -> None:
        self.status = "SCANNING FOR BLUETOOTH DEVICES; PUT THE CONTROLLER IN PAIRING MODE"
        self.bluetooth_entries = bluetooth_devices(scan=True)
        self.overlay_selection = 0
        self.status = (
            f"FOUND {len(self.bluetooth_entries)} BLUETOOTH DEVICES"
            if self.bluetooth_entries else "NO BLUETOOTH DEVICES FOUND; PRESS X TO SCAN AGAIN"
        )

    def _select_bluetooth(self, device: dict[str, Any]) -> None:
        address = str(device.get("address", ""))
        name = str(device.get("name", "BLUETOOTH DEVICE"))
        if not address:
            return
        self.status = f"PAIRING / CONNECTING {name}"
        success, message = pair_or_connect_bluetooth(address)
        self.status = f"CONNECTED {name}" if success else f"BLUETOOTH FAILED: {message[-80:]}"
        self.bluetooth_entries = bluetooth_devices(scan=False)

    def _disconnect_selected_bluetooth(self) -> None:
        if self.overlay_selection >= len(self.bluetooth_entries):
            return
        device = self.bluetooth_entries[self.overlay_selection]
        address = str(device.get("address", ""))
        name = str(device.get("name", "BLUETOOTH DEVICE"))
        success, message = disconnect_bluetooth(address)
        self.status = f"DISCONNECTED {name}" if success else f"DISCONNECT FAILED: {message[-80:]}"
        self.bluetooth_entries = bluetooth_devices(scan=False)

    def _entries_for_screen(self) -> list[dict[str, Any]]:
        if self.screen_name == "play":
            return [item for item in self.library if is_external_entry(item)]
        return self.library

    def _library_entries(self) -> list[dict[str, Any]]:
        return [item for item in self.library if is_installed_game(item)]

    def _library_systems(self) -> list[tuple[str, int]]:
        grouped: dict[str, int] = {}
        for entry in self._library_entries():
            platform = str(entry.get("platform") or entry.get("system") or "other")
            grouped[platform] = grouped.get(platform, 0) + 1
        return sorted(grouped.items(), key=lambda item: self._system_label(item[0]))

    def _library_games_for_system(self) -> list[dict[str, Any]]:
        return [
            entry for entry in self._library_entries()
            if str(entry.get("platform") or entry.get("system") or "other") == self.library_system
        ]

    def _store_entries(self) -> list[dict[str, Any]]:
        return [item for item in self.library if is_internal_content(item)]

    def _launch_3d_library(self) -> None:
        """Temporarily hand the display to the full OpenGL store renderer."""
        renderer = next((path for path in THREE_D_LIBRARY_PATHS if path.is_file()), None)
        if renderer is None:
            self._open("3d-library")
            self.status = "OPENGL STORE IS NOT INSTALLED; USING COMPATIBILITY VIEW"
            return
        THREE_D_SELECTION_PATH.unlink(missing_ok=True)
        self._pause_theme_animation()
        pygame.display.quit()
        result = None
        try:
            result = subprocess.run(
                [sys.executable, str(renderer), "--selection-file", str(THREE_D_SELECTION_PATH)],
                check=False,
                env={**os.environ, "PYGAME_HIDE_SUPPORT_PROMPT": "1"},
            )
        except OSError as exc:
            self.status = f"3D PLAZA FAILED: {exc}"
        finally:
            pygame.display.init()
            self.screen = pygame.display.set_mode(
                LOGICAL_SIZE,
                pygame.FULLSCREEN | pygame.SCALED | pygame.DOUBLEBUF,
                vsync=1,
            )
            self.canvas = self.screen
            self.cover_images.clear()
            # The standalone OpenGL store owns the controller while running.
            # Drain its final axis/hat events before the SDL dashboard resumes;
            # otherwise the first D-pad press can inherit a reversed stale move.
            pygame.event.clear()
            self.axis_latch = {"x": 0, "y": 0}
            now = time.monotonic()
            self.axis_repeat_at = {"x": now, "y": now}
            self.store_axes = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}
            self.view_down = False
            self.menu_down = False
            self._resume_theme_animation()
        if result is not None and result.returncode != 0:
            self.status = f"3D PLAZA FAILED: {result.returncode}; USING COMPATIBILITY VIEW"
            self._open("3d-library")
            return
        selected = read_json(THREE_D_SELECTION_PATH, {})
        content_id = str(selected.get("content_id", "")) if isinstance(selected, dict) else ""
        action = str(selected.get("action", "")) if isinstance(selected, dict) else ""
        if action == "play-vod" and isinstance(selected, dict) and isinstance(selected.get("media"), dict):
            self._play_tv_channel({str(key): str(value) for key, value in selected["media"].items()})
            if self.running:
                self._launch_3d_library()
            return
        selected_entry = next(
            (entry for entry in self.library if str(entry.get("content_id", "")) == content_id),
            None,
        )
        if selected_entry is not None and action == "install":
            self._start_install(selected_entry)
            return
        if selected_entry is not None and action == "launch":
            self._launch(selected_entry, return_screen="3d-library")
            return
        entries = self._store_entries()
        index = next((i for i, entry in enumerate(entries) if str(entry.get("content_id", "")) == content_id), None)
        if index is not None:
            self.store_detail_index = index
            self.store_case_angle = -0.16
            self._open("3d-details")
        else:
            self._open("home")

    def _launch(self, entry: dict[str, Any], return_screen: str = "home") -> None:
        content_id = str(entry.get("content_id", ""))
        if not content_id:
            return
        if str(entry.get("platform", "")).lower() == "dvd-video":
            self._play_dvd_movie(entry)
            self._return_after_launch(return_screen)
            return
        title = str(entry.get("title", "Unknown"))
        if is_music_entry(entry):
            self._play_music_entry(entry)
            self._return_after_launch(return_screen)
            return
        if is_movie_entry(entry):
            path = str(entry.get("path", ""))
            self._run_media_process(
                ["/usr/bin/mpv", "--fullscreen", "--no-terminal", "--input-default-bindings=yes", path],
                f"PLAYING {title.upper()}",
            )
            self._return_after_launch(return_screen)
            return
        self._prepare_game_environment(entry, content_id)
        # Optical PS1/PS2 entries are discovered by the shell after the media
        # index is built.  Register that temporary, read-only entry for the
        # control process so its stable ID resolves like every other game.
        runtime_index = LIBRARY_PATH
        if str(entry.get("source_root", "")).startswith(str(REMOVABLE_ROOT)):
            try:
                indexed = read_json(runtime_index, [])
                if isinstance(indexed, list) and not any(
                    str(item.get("content_id", "")) == content_id for item in indexed
                ):
                    indexed.insert(0, entry)
                    temporary = runtime_index.with_suffix(".json.tmp")
                    temporary.write_text(json.dumps(indexed, indent=2), encoding="utf-8")
                    temporary.replace(runtime_index)
            except OSError as exc:
                self.status = f"DISC LAUNCH INDEX FAILED: {exc}"
                return
        self.status = f"LAUNCHING {title.upper()}"
        # Hand the display to the game from a neutral black frame. Showing the
        # dashboard here made a normal Wine/runtime startup look frozen.
        self.canvas.fill((0, 0, 0))
        pygame.display.flip()
        display_released = False
        self._pause_theme_animation()
        try:
            # Release SDL's fullscreen window before a standalone emulator
            # claims the display.  Without this, launching from the normal
            # Library can leave DuckStation windowed while 3D Library works.
            pygame.display.quit()
            display_released = True
            result = subprocess.run(
                [sys.executable, "-m", "pulsearc.control", "launch", content_id, "--profile", self.profile_id],
                check=False,
                env=pulsearc_control_env(),
            )
            self.status = "GAME CLOSED" if result.returncode == 0 else f"LAUNCH FAILED: {result.returncode}"
        except OSError as exc:
            self.status = f"LAUNCH FAILED: {exc}"
        finally:
            if display_released:
                pygame.display.init()
                self.screen = pygame.display.set_mode(
                    LOGICAL_SIZE,
                    pygame.FULLSCREEN | pygame.SCALED | pygame.DOUBLEBUF,
                    vsync=1,
                )
                self.canvas = self.screen
                pygame.display.set_caption("PulseArc")
                pygame.mouse.set_visible(False)
            self._resume_theme_animation()
        # Discard the View+Menu release events used to leave an emulator so
        # they cannot also move or activate the dashboard behind it.
        pygame.event.clear()
        self.view_down = False
        self.menu_down = False
        self.axis_latch = {"x": 0, "y": 0}
        self.store_axes = {axis: 0.0 for axis in self.store_axes}
        self._return_after_launch(return_screen)

    def _install_external_entry(self, entry: dict[str, Any], quiet: bool = False) -> str:
        """Copy one removable game into the managed internal library safely."""
        source_path = Path(str(entry.get("path", "")))
        source_root = Path(str(entry.get("source_root", "")))
        try:
            removable_root = REMOVABLE_ROOT.resolve()
            path_resolved = source_path.resolve(strict=True)
            root_resolved = source_root.resolve(strict=True)
        except (OSError, ValueError):
            if not quiet:
                self.status = "INSTALL FAILED: SOURCE MEDIA IS NO LONGER AVAILABLE"
            return "failed"
        if not (path_resolved.is_relative_to(removable_root) and root_resolved.is_relative_to(removable_root)):
            if not quiet:
                self.status = "INSTALL FAILED: SOURCE IS NOT REMOVABLE MEDIA"
            return "failed"
        if source_path.is_symlink() or source_root.is_symlink():
            if not quiet:
                self.status = "INSTALL FAILED: SYMBOLIC LINKS ARE NOT ACCEPTED"
            return "failed"

        platform = re.sub(r"[^a-z0-9-]+", "-", str(entry.get("platform", "other")).lower()).strip("-") or "other"
        title = str(entry.get("title") or source_path.stem or "game")
        slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-") or str(entry.get("content_id", "game"))[:16]
        destination = Path("/var/lib/pulsearc/library/games") / platform / slug
        staging = destination.with_name(f".{destination.name}.installing")
        if destination.exists():
            if not quiet:
                self.status = f"{title.upper()} IS ALREADY INSTALLED"
            return "skipped"
        try:
            if staging.exists():
                shutil.rmtree(staging)
            content = staging / "content"
            content.mkdir(parents=True)
            # Manifests and portable PC games need their companion files;
            # ordinary loose ROMs copy only the selected game file.
            manifest = next(
                (
                    candidate for candidate in root_resolved.iterdir()
                    if candidate.is_file()
                    and (
                        candidate.name.casefold() == "pulsearc.toml"
                        or candidate.suffix.casefold() == ".kzi"
                    )
                ),
                None,
            )
            if manifest is not None and root_resolved != removable_root:
                shutil.copytree(root_resolved, content, dirs_exist_ok=True, symlinks=False)
            else:
                shutil.copy2(path_resolved, content / path_resolved.name, follow_symlinks=False)
            cover_path = Path(str(entry.get("cover_path", "")))
            if cover_path.is_file() and cover_path.resolve().is_relative_to(removable_root):
                shutil.copy2(cover_path, staging / "cover.png", follow_symlinks=False)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(destination)
            if not quiet:
                self.status = f"INSTALLED {title.upper()}"
            return "installed"
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            if not quiet:
                self.status = f"INSTALL FAILED: {exc}"
            return "failed"

    @staticmethod
    def _optical_device_size(device: Path) -> int:
        """Return the kernel-reported readable size without scanning the disc."""
        try:
            sectors = int((Path("/sys/class/block") / device.name / "size").read_text().strip())
            return sectors * 512
        except (OSError, ValueError):
            return 0

    def _start_install(self, entry: dict[str, Any]) -> None:
        if self.install_thread is not None and self.install_thread.is_alive():
            self.status = "AN INSTALL IS ALREADY RUNNING"
            self._open("install-progress")
            return
        self.install_title = str(entry.get("title") or "Game")
        self.install_progress = 0.0
        self.install_bytes = 0
        self.install_total = 0
        self.install_started = time.monotonic()
        self.install_phase = "PREPARING"
        self.install_result = ""
        self.install_return_screen = "play"
        self._open("install-progress")
        self.install_thread = threading.Thread(
            target=self._install_worker,
            args=(dict(entry),),
            name="pulsearc-installer",
            daemon=True,
        )
        self.install_thread.start()

    def _install_worker(self, entry: dict[str, Any]) -> None:
        try:
            source = Path(str(entry.get("path", "")))
            if str(source).startswith("/dev/"):
                result = self._install_optical_entry(entry, source)
            else:
                self.install_phase = "COPYING"
                result = self._install_external_entry(entry, quiet=True)
                self.install_progress = 1.0 if result in {"installed", "skipped"} else self.install_progress
        except Exception as exc:
            # A failed or damaged disc must report an error without taking the
            # dashboard down with its worker thread.
            result = "failed"
            self.status = f"INSTALL FAILED: {exc}"
        self.install_result = result
        if result in {"installed", "skipped"}:
            # Do not depend on a long-running/older media daemon noticing the
            # directory rename.  Registration is part of a successful install.
            if not self._rebuild_internal_library_index():
                self.install_result = "failed"
                self.install_phase = "FAILED"
                return
        if result == "installed":
            self.install_phase = "COMPLETE"
            self.status = f"INSTALLED {self.install_title.upper()}"
        elif result == "skipped":
            self.install_phase = "ALREADY INSTALLED"
            self.status = f"{self.install_title.upper()} IS ALREADY INSTALLED"
        else:
            self.install_phase = "FAILED"
            if not self.status.startswith("INSTALL FAILED"):
                self.status = f"INSTALL FAILED: {self.install_title.upper()}"

    def _rebuild_internal_library_index(self) -> bool:
        """Atomically merge a fresh internal scan with mounted-media entries."""
        for path in reversed(PULSEARC_CORE_PATHS):
            value = str(path)
            if path.is_dir() and value not in sys.path:
                sys.path.insert(0, value)
        try:
            from pulsearc.scanner import scan

            internal_root = Path("/var/lib/pulsearc/library").resolve()
            internal_rows = [asdict(item) for item in scan(internal_root)]
            current = read_json(LIBRARY_PATH, [])
            external_rows = [
                item for item in current if isinstance(item, dict)
                and str(Path(str(item.get("source_root", ""))).resolve()) != str(internal_root)
            ] if isinstance(current, list) else []
            merged: dict[str, dict[str, Any]] = {}
            for item in [*internal_rows, *external_rows]:
                content_id = str(item.get("content_id", ""))
                if content_id:
                    merged.setdefault(content_id, item)
            LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = LIBRARY_PATH.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(list(merged.values()), indent=2), encoding="utf-8")
            temporary.replace(LIBRARY_PATH)
            self._refresh_state(force=True)
            return True
        except (ImportError, OSError, ValueError) as exc:
            self.status = f"INSTALL FAILED: LIBRARY REGISTRATION: {exc}"
            return False

    def _install_optical_entry(self, entry: dict[str, Any], device: Path) -> str:
        platform = re.sub(r"[^a-z0-9-]+", "-", str(entry.get("platform", "other")).lower()).strip("-") or "other"
        if platform not in {"playstation", "playstation-2"} or device not in {Path("/dev/sr0"), Path("/dev/cdrom")}:
            self.status = "INSTALL FAILED: THIS OPTICAL FORMAT CANNOT BE RIPPED YET"
            return "failed"
        title = str(entry.get("title") or ("PlayStation 2 Game" if platform == "playstation-2" else "PlayStation Game"))
        slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-") or str(entry.get("content_id", "game"))[:16]
        destination = Path("/var/lib/pulsearc/library/games") / platform / slug
        staging = destination.with_name(f".{destination.name}.installing")
        if destination.exists():
            return "skipped"
        formatted_size = self._optical_device_size(device)
        # Linux exposes a data CD through /dev/sr0 as 2048-byte logical
        # blocks. PlayStation CDs are Mode 2 media, however, and must be read
        # as 2352-byte raw sectors or the drive reports EIO/"Illegal mode for
        # this track" near the start of the disc.
        sector_count = formatted_size // 2048 if platform == "playstation" else 0
        total = sector_count * 2352 if sector_count else formatted_size
        self.install_total = total
        self.install_phase = "RIPPING DISC"
        try:
            shutil.rmtree(staging, ignore_errors=True)
            content = staging / "content"
            content.mkdir(parents=True)
            if platform == "playstation":
                image = content / f"{slug}.bin"
                cue = content / f"{slug}.cue"
                cd_read = shutil.which("cd-read")
                if cd_read is None or sector_count <= 0:
                    raise OSError("raw PlayStation CD reader is unavailable")
                log_path = staging / "cd-read.log"
                with log_path.open("wb") as log:
                    process = subprocess.Popen(
                        [
                            cd_read,
                            "--mode=any",
                            "--start=0",
                            f"--number={sector_count}",
                            f"--cdrom-device={device}",
                            f"--output-file={image}",
                        ],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                    while process.poll() is None:
                        try:
                            copied = image.stat().st_size
                        except OSError:
                            copied = 0
                        self.install_bytes = copied
                        if total > 0:
                            self.install_progress = min(0.995, copied / total)
                        time.sleep(0.2)
                    return_code = process.wait()
                copied = image.stat().st_size if image.exists() else 0
                self.install_bytes = copied
                if return_code != 0:
                    details = log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                    raise OSError(details[-1][-180:] if details else f"raw CD reader exited {return_code}")
                cue.write_text(
                    f'FILE "{image.name}" BINARY\n'
                    "  TRACK 01 MODE2/2352\n"
                    "    INDEX 01 00:00:00\n",
                    encoding="ascii",
                )
                entrypoint = cue
            else:
                image = content / f"{slug}.iso"
                copied = 0
                with device.open("rb", buffering=0) as source, image.open("wb", buffering=0) as output:
                    while total <= 0 or copied < total:
                        requested = min(1024 * 1024, total - copied) if total > 0 else 1024 * 1024
                        block = source.read(requested)
                        if not block:
                            break
                        output.write(block)
                        copied += len(block)
                        self.install_bytes = copied
                        if total > 0:
                            self.install_progress = min(0.995, copied / total)
                    output.flush()
                    os.fsync(output.fileno())
                entrypoint = image
            if copied < 32 * 1024 * 1024 or (total > 0 and copied < total * 0.98):
                raise OSError(f"disc read ended early at {copied / 1048576:.1f} MB")
            self.install_phase = "FINALIZING"
            manifest = staging / "pulsearc.toml"
            manifest.write_text(
                "[game]\n"
                f"title = {json.dumps(title)}\n"
                f"platform = {json.dumps(platform)}\n"
                f"entrypoint = {json.dumps('content/' + entrypoint.name)}\n",
                encoding="utf-8",
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging.replace(destination)
            self.install_progress = 1.0
            return "installed"
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            self.status = f"INSTALL FAILED: {exc}"
            return "failed"

    def _install_all_external_games(self) -> None:
        """Install every removable game while ignoring music, movies and live discs."""
        visible_games = [
            entry for entry in self._entries_for_screen()
            if not is_music_entry(entry)
            and not is_movie_entry(entry)
        ]
        optical = [entry for entry in visible_games if str(entry.get("path", "")).startswith("/dev/")]
        candidates = [entry for entry in visible_games if entry not in optical]
        # With one physical game inserted, the prominent Install row should
        # behave like INSTALL DISC. Requiring the less-obvious X shortcut made
        # the action appear broken even though the optical worker existed.
        if not candidates and len(optical) == 1:
            self._start_install(optical[0])
            return
        if not candidates:
            self.status = "NO INSTALLABLE USB OR SD GAMES FOUND"
            return
        installed = skipped = failed = 0
        for entry in candidates:
            result = self._install_external_entry(entry, quiet=True)
            installed += result == "installed"
            skipped += result == "skipped"
            failed += result == "failed"
        self.status = f"INSTALL ALL: {installed} ADDED, {skipped} ALREADY THERE, {failed} FAILED"
        self._refresh_state(force=True)

    def _return_after_launch(self, return_screen: str) -> None:
        if return_screen == "3d-library":
            self._launch_3d_library()
        else:
            self._open(return_screen)

    def _play_dvd_movie(self, entry: dict[str, Any]) -> None:
        # Kodi's VideoPlayer is used strictly as a fullscreen DVD-navigation
        # engine.  The wrapper skips Kodi's media-center UI, invokes PlayDisc,
        # and exits with PulseArc so playback cannot continue behind the menu.
        # mpv remains a main-title fallback on minimal/offline installations.
        device = str(entry.get("path") or "/dev/sr0")
        kodi_player = Path.home() / ".local/bin/pulsearc-kodi-dvd"
        if kodi_player.is_file():
            exited_by_user, return_code, elapsed = self._run_media_process(
                [str(kodi_player)],
                "OPENING DVD MENU",
                dvd_navigation=True,
            )
            if exited_by_user or return_code == 0 or elapsed >= 5.0:
                return
            self.status = "DVD MENU UNAVAILABLE; PLAYING MAIN TITLE"
            self._draw()
            pygame.display.flip()
        self._run_media_process(
            [
                "/usr/bin/env",
                f"LD_LIBRARY_PATH={Path.home() / '.local/lib'}",
                "/usr/bin/mpv",
                "--fullscreen",
                "--no-terminal",
                "--input-default-bindings=yes",
                f"--dvd-device={device}",
                "dvd://1",
            ],
            "PLAYING DVD TITLE (MENU PLAYER NOT INSTALLED)",
        )

    def _prepare_game_environment(self, entry: dict[str, Any], content_id: str) -> None:
        """Apply safe runtime defaults and privately imported firmware."""
        platform = str(entry.get("platform") or entry.get("system") or "").lower()
        save_root = PROFILES_PATH.parent / self.profile_id / "games" / content_id
        firmware_root = Path("/var/lib/pulsearc/firmware")
        if str(entry.get("runner", "")).startswith("retroarch"):
            self._prepare_retroarch_config(save_root)
            self._prepare_core_options(platform, save_root)
        links: list[tuple[Path, Path]] = []
        if platform == "playstation":
            source = firmware_root / "ps1/scph5501.bin"
            links.extend((
                (source, save_root / "data/duckstation/bios/scph5501.bin"),
                (source, save_root / "config/duckstation/bios/scph5501.bin"),
                (source, save_root / "config/retroarch/system/scph5501.bin"),
            ))
        elif platform == "playstation-2":
            source = firmware_root / "ps2/scph10000.bin"
            links.extend((
                (source, save_root / "config/PCSX2/bios/scph10000.bin"),
                (source, save_root / "data/PCSX2/bios/scph10000.bin"),
            ))
        elif platform == "wii-u":
            source = firmware_root / "wiiu/keys.txt"
            links.extend((
                (source, save_root / "data/Cemu/keys.txt"),
                (source, save_root / "config/Cemu/keys.txt"),
                (source, save_root / "data/cemu/keys.txt"),
                (source, save_root / "config/cemu/keys.txt"),
            ))
        for source, destination in links:
            if not source.is_file():
                continue
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.is_symlink() or destination.exists():
                    destination.unlink()
                destination.symlink_to(source)
            except OSError as exc:
                self.status = f"FIRMWARE LINK WARNING: {exc}"

    def _prepare_retroarch_config(self, save_root: Path) -> None:
        config = save_root / "config/retroarch/retroarch.cfg"
        defaults = {
            "video_fullscreen": "true",
            "video_windowed_fullscreen": "true",
            "audio_driver": "pipewire",
            "audio_device": "",
            "audio_enable": "true",
            "audio_mute_enable": "false",
            "audio_volume": "0.000000",
            "input_driver": "x",
            "input_joypad_driver": "udev",
            "input_autodetect_enable": "true",
            "input_player1_joypad_index": "0",
            "input_player1_a_btn": "1",
            "input_player1_b_btn": "0",
            "input_player1_x_btn": "3",
            "input_player1_y_btn": "2",
            "input_player1_l_btn": "4",
            "input_player1_r_btn": "5",
            "input_player1_select_btn": "6",
            "input_player1_start_btn": "7",
            "input_player1_l3_btn": "9",
            "input_player1_r3_btn": "10",
            "input_player1_up_btn": "h0up",
            "input_player1_down_btn": "h0down",
            "input_player1_left_btn": "h0left",
            "input_player1_right_btn": "h0right",
            "input_player1_l_x_minus_axis": "-0",
            "input_player1_l_x_plus_axis": "+0",
            "input_player1_l_y_minus_axis": "-1",
            "input_player1_l_y_plus_axis": "+1",
            "input_player1_r_x_minus_axis": "-3",
            "input_player1_r_x_plus_axis": "+3",
            "input_player1_r_y_minus_axis": "-4",
            "input_player1_r_y_plus_axis": "+4",
            "input_enable_hotkey_btn": "6",
            "input_exit_emulator_btn": "7",
        }
        try:
            config.parent.mkdir(parents=True, exist_ok=True)
            lines = config.read_text(encoding="utf-8", errors="replace").splitlines() if config.exists() else []
            rewritten: list[str] = []
            remaining = dict(defaults)
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
        except OSError as exc:
            self.status = f"CONTROLLER CONFIG WARNING: {exc}"

    def _prepare_core_options(self, platform: str, save_root: Path) -> None:
        if platform != "nintendo-64":
            return
        runtime_settings = self.settings.get("runtime_resolution", {})
        scale = str(runtime_settings.get("nintendo-64", "2x")) if isinstance(runtime_settings, dict) else "2x"
        sizes = {
            "1x": ("640x480", "960x540"),
            "2x": ("1280x960", "1920x1080"),
            "3x": ("1920x1440", "2880x1620"),
            "4x": ("2560x1920", "3840x2160"),
        }
        size_43, size_169 = sizes.get(scale, sizes["2x"])
        options = save_root / "config/retroarch/config/Mupen64Plus-Next/Mupen64Plus-Next.opt"
        replacements = {
            "mupen64plus-43screensize": size_43,
            "mupen64plus-169screensize": size_169,
            "mupen64plus-rdp-plugin": "gliden64",
            "mupen64plus-rsp-plugin": "hle",
        }
        try:
            options.parent.mkdir(parents=True, exist_ok=True)
            lines = options.read_text(encoding="utf-8", errors="replace").splitlines() if options.exists() else []
            rewritten: list[str] = []
            remaining = dict(replacements)
            for line in lines:
                key = line.split("=", 1)[0].strip() if "=" in line else ""
                if key in remaining:
                    rewritten.append(f'{key} = "{remaining.pop(key)}"')
                else:
                    rewritten.append(line)
            rewritten.extend(f'{key} = "{value}"' for key, value in remaining.items())
            temporary = options.with_suffix(".opt.tmp")
            temporary.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
            temporary.replace(options)
        except OSError as exc:
            self.status = f"RUNTIME CONFIG WARNING: {exc}"

    def _power(self, index: int) -> None:
        if index == 0:
            raise SystemExit(75)
        action = "reboot" if index == 1 else "poweroff"
        subprocess.Popen(["/usr/bin/sudo", "/usr/bin/systemctl", action])

    def _settings_action(self, index: int) -> None:
        if index == 0:
            values = ("auto", "1080p", "720p")
            current = str(self.settings.get("display_policy", "auto"))
            self.settings["display_policy"] = values[(values.index(current) + 1) % len(values)] if current in values else "auto"
        elif index == 1:
            values = ("hdmi", "auto", "analog")
            current = str(self.settings.get("audio_policy", "hdmi"))
            self.settings["audio_policy"] = values[(values.index(current) + 1) % len(values)] if current in values else "hdmi"
            if self.settings["audio_policy"] == "hdmi":
                subprocess.run([str(Path.home() / ".local/bin/pulsearc-audio-select")], check=False)
        elif index == 2:
            values = (25, 50, 75, 100)
            try:
                current = int(self.settings.get("master_volume", 100))
            except (TypeError, ValueError):
                current = 100
            self.settings["master_volume"] = values[(values.index(current) + 1) % len(values)] if current in values else 100
            self._apply_master_volume()
        elif index == 3:
            self.settings["menu_sounds"] = not bool(self.settings.get("menu_sounds", True))
        elif index == 4:
            self.settings["artwork_downloads"] = not bool(self.settings.get("artwork_downloads", True))
        elif index == 5:
            current = str(self.settings.get("start_screen", "home"))
            self.settings["start_screen"] = "3d-library" if current == "home" else "home"
        elif index == 6:
            self._open("runtime-settings")
            return
        elif index == 7:
            self._open("controllers")
            return
        else:
            self._back()
            return
        self._save_settings()
        self.status = "SETTINGS SAVED"

    def _runtime_settings_action(self, index: int) -> None:
        if index == 0:
            values = ("1x", "2x", "3x", "4x")
            runtime = self.settings.setdefault("runtime_resolution", {})
            if not isinstance(runtime, dict):
                runtime = {}
                self.settings["runtime_resolution"] = runtime
            current = str(runtime.get("nintendo-64", "2x"))
            runtime["nintendo-64"] = values[(values.index(current) + 1) % len(values)] if current in values else "2x"
            self._save_settings()
            self.status = "N64 INTERNAL RESOLUTION SAVED"
        else:
            self._back()

    def _run_media_process(
        self,
        command: list[str],
        label: str,
        dvd_navigation: bool = False,
        projectm_visuals: bool = False,
        recording_channel: dict[str, str] | None = None,
    ) -> tuple[bool, int, float]:
        self.status = label
        self._draw()
        pygame.display.flip()
        is_mpv = any(Path(part).name == "mpv" for part in command)
        is_vlc = any(
            Path(part).name in {"vlc", "cvlc", "pulsearc-vlc", "kodi", "kodi-standalone", "pulsearc-kodi-dvd"}
            for part in command
        )
        ipc_path = Path(f"/tmp/pulsearc-mpv-{os.getpid()}-{time.monotonic_ns()}.sock") if is_mpv else None
        if ipc_path is not None:
            command = [*command[:-1], f"--input-ipc-server={ipc_path}", command[-1]]
        started = time.monotonic()
        exit_requested = False
        return_code = 1
        visualizer: subprocess.Popen[Any] | None = None
        self._pause_theme_animation()
        try:
            process = subprocess.Popen(command)
            if projectm_visuals:
                # Let MPV create its PulseAudio/PipeWire playback stream first
                # so projectM immediately locks onto the active monitor source.
                time.sleep(0.35)
                visualizer = self._start_projectm_visualizer()
            media_axis_latch = {0: 0, 1: 0}
            while process.poll() is None:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                        exit_requested = True
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            exit_requested = True
                        elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
                            self._media_key(ipc_path, is_vlc, "Return", ["discnav", "select"] if dvd_navigation else ["cycle", "pause"])
                        elif event.key == pygame.K_LEFT:
                            self._media_key(ipc_path, is_vlc, "Left", ["discnav", "left"] if dvd_navigation else ["seek", -10, "relative"])
                        elif event.key == pygame.K_RIGHT:
                            self._media_key(ipc_path, is_vlc, "Right", ["discnav", "right"] if dvd_navigation else ["seek", 10, "relative"])
                        elif event.key == pygame.K_UP:
                            self._media_key(ipc_path, is_vlc, "Up", ["discnav", "up"] if dvd_navigation else ["add", "chapter", 1])
                        elif event.key == pygame.K_DOWN:
                            self._media_key(ipc_path, is_vlc, "Down", ["discnav", "down"] if dvd_navigation else ["add", "chapter", -1])
                        elif event.key == pygame.K_r and recording_channel is not None:
                            message = self._toggle_dvr_channel(recording_channel)
                            self._mpv_command(ipc_path, ["show-text", message, 3500])
                    elif event.type == pygame.JOYBUTTONDOWN:
                        if event.button == 1:
                            exit_requested = True
                        elif event.button == 0:
                            self._media_key(ipc_path, is_vlc, "Return", ["discnav", "select"] if dvd_navigation else ["cycle", "pause"])
                        elif event.button == 4:
                            self._media_key(ipc_path, is_vlc, "Page_Up", ["discnav", "prev"] if dvd_navigation else ["add", "chapter", -1])
                        elif event.button == 5:
                            if recording_channel is not None:
                                message = self._toggle_dvr_channel(recording_channel)
                                self._mpv_command(ipc_path, ["show-text", message, 3500])
                            else:
                                self._media_key(ipc_path, is_vlc, "m", ["discnav", "menu"] if dvd_navigation else ["add", "chapter", 1])
                        elif event.button == 6:
                            self.view_down = True
                        elif event.button == 7:
                            self.menu_down = True
                        if self.view_down and self.menu_down:
                            exit_requested = True
                    elif event.type == pygame.JOYBUTTONUP:
                        if event.button == 6:
                            self.view_down = False
                        elif event.button == 7:
                            self.menu_down = False
                    elif event.type == pygame.JOYHATMOTION:
                        if event.value[0]:
                            self._media_key(
                                ipc_path, is_vlc, "Right" if event.value[0] > 0 else "Left",
                                ["discnav", "right" if event.value[0] > 0 else "left"]
                                if dvd_navigation else ["seek", 10 * event.value[0], "relative"],
                            )
                        if event.value[1]:
                            self._media_key(
                                ipc_path, is_vlc, "Up" if event.value[1] > 0 else "Down",
                                ["discnav", "up" if event.value[1] > 0 else "down"]
                                if dvd_navigation else ["add", "chapter", event.value[1]],
                            )
                    elif event.type == pygame.JOYAXISMOTION and event.axis in media_axis_latch:
                        direction = 1 if event.value > 0.65 else -1 if event.value < -0.65 else 0
                        if direction and media_axis_latch[event.axis] != direction:
                            if event.axis == 0:
                                self._media_key(
                                    ipc_path, is_vlc, "Right" if direction > 0 else "Left",
                                    ["discnav", "right" if direction > 0 else "left"]
                                    if dvd_navigation else ["seek", 10 * direction, "relative"],
                                )
                            else:
                                self._media_key(
                                    ipc_path, is_vlc, "Down" if direction > 0 else "Up",
                                    ["discnav", "down" if direction > 0 else "up"]
                                    if dvd_navigation else ["add", "chapter", -direction],
                                )
                        media_axis_latch[event.axis] = direction
                if exit_requested:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                    break
                time.sleep(0.02)
            return_code = process.returncode if process.returncode is not None else 0
            self.status = "MEDIA CLOSED" if exit_requested or return_code == 0 else f"MEDIA FAILED: {return_code}"
        except OSError as exc:
            self.status = f"MEDIA FAILED: {exc}"
        finally:
            if visualizer is not None and visualizer.poll() is None:
                visualizer.terminate()
                try:
                    visualizer.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    visualizer.kill()
                    visualizer.wait(timeout=2)
            if ipc_path is not None:
                ipc_path.unlink(missing_ok=True)
            self._resume_theme_animation()
        return exit_requested, return_code, time.monotonic() - started

    @staticmethod
    def _mpv_command(ipc_path: Path | None, command: list[Any]) -> None:
        if ipc_path is None or not ipc_path.exists():
            return
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.15)
                client.connect(str(ipc_path))
                client.sendall((json.dumps({"command": command}) + "\n").encode("utf-8"))
        except OSError:
            pass

    @classmethod
    def _media_key(cls, ipc_path: Path | None, is_vlc: bool, key: str, command: list[Any]) -> None:
        # Some Xbox-compatible pads report a held D-pad direction more than
        # once, and VLC may create both a controller and a video window. Keep
        # one physical press from becoming two menu moves or chapter skips.
        now = time.monotonic()
        last_keys = getattr(cls, "_media_key_times", {})
        if now - float(last_keys.get(key, 0.0)) < 0.16:
            return
        last_keys[key] = now
        cls._media_key_times = last_keys
        if not is_vlc:
            cls._mpv_command(ipc_path, command)
            return
        try:
            active = subprocess.run(
                [cls._xdotool_executable(), "getactivewindow"],
                check=False,
                capture_output=True,
                text=True,
                timeout=0.4,
            ).stdout.strip()
            window_class = ""
            if active:
                window_class = subprocess.run(
                    [cls._xdotool_executable(), "getwindowclassname", active],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=0.4,
                ).stdout.strip().lower()
            if not active or not any(player in window_class for player in ("vlc", "kodi")):
                visible: list[str] = []
                for player_class in ("kodi", "vlc"):
                    visible.extend(subprocess.run(
                        [cls._xdotool_executable(), "search", "--onlyvisible", "--class", player_class],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=0.4,
                    ).stdout.splitlines())
                active = visible[-1].strip() if visible else ""
            if not active:
                return
            subprocess.run(
                [cls._xdotool_executable(), "key", "--window", active, "--clearmodifiers", key],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=0.5,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _play_audio_cd(self) -> None:
        device = next((path for path in ("/dev/sr0", "/dev/cdrom") if Path(path).exists()), "")
        if not device:
            self.status = "NO OPTICAL DRIVE DETECTED"
            self._back()
            return
        self._run_media_process(
            ["/usr/bin/mpv", "--no-video", "--no-terminal", f"--cdrom-device={device}", "cdda://"],
            "PLAYING AUDIO CD",
            projectm_visuals=True,
        )

    def _play_detected_music(self) -> None:
        paths = [str(item.get("path", "")) for item in self._music_entries()]
        paths = [path for path in paths if path]
        if not paths:
            self.status = "NO MUSIC FILES DETECTED"
            self._back()
            return
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix="pulsearc-music-", suffix=".m3u", delete=False) as playlist:
            for path in paths:
                playlist.write(path + "\n")
            playlist_path = playlist.name
        try:
            self._run_media_process(
                ["/usr/bin/mpv", "--no-video", "--no-terminal", "--shuffle", f"--playlist={playlist_path}"],
                "SHUFFLING MUSIC",
                projectm_visuals=True,
            )
        finally:
            Path(playlist_path).unlink(missing_ok=True)

    def _music_entries(self) -> list[dict[str, Any]]:
        return [item for item in self.library if is_music_entry(item)]

    def _play_music_entry(self, entry: dict[str, Any]) -> None:
        path = str(entry.get("path", ""))
        if not path:
            self.status = "MUSIC FILE IS MISSING"
            return
        self._run_media_process(
            ["/usr/bin/mpv", "--no-video", "--no-terminal", "--input-default-bindings=yes", path],
            f"PLAYING {str(entry.get('title', 'MUSIC')).upper()}",
            projectm_visuals=True,
        )

    def _play_radio_station(self, station: dict[str, str]) -> None:
        name = str(station.get("name", "INTERNET RADIO"))
        url = str(station.get("url", ""))
        if not url:
            self.status = "RADIO STATION URL IS MISSING"
            return
        _exit_requested, return_code, elapsed = self._run_media_process(
            [
                "/usr/bin/mpv",
                "--no-video",
                "--no-terminal",
                "--cache=yes",
                "--cache-secs=8",
                "--network-timeout=12",
                "--input-default-bindings=yes",
                url,
            ],
            f"STREAMING {name.upper()}",
            projectm_visuals=True,
        )
        if return_code != 0 and elapsed < 15:
            self.status = f"{name.upper()} IS CURRENTLY UNAVAILABLE"

    def _tv_sources(self) -> list[dict[str, Any]]:
        return [*(dict(source) for source in BUILTIN_TV_SOURCES), *load_saved_sources(TV_SOURCES_PATH)]

    def _tv_channels_for_group(self) -> list[dict[str, str]]:
        return [channel for channel in self.tv_channels if channel.get("group", "OTHER") == self.tv_group]

    def _refresh_tv_channels(self, selected_source: dict[str, Any] | None = None) -> None:
        sources = [selected_source] if selected_source is not None else self._tv_sources()
        self.tv_active_source = dict(selected_source) if selected_source is not None else None
        self.status = "DOWNLOADING TV CHANNEL LISTS"
        self._draw()
        pygame.display.flip()
        channels: list[dict[str, str]] = []
        cache_count = 0
        failed: list[str] = []
        for source in sources:
            if source is None:
                continue
            try:
                values, used_cache = fetch_source(source, TV_CACHE_ROOT)
            except (OSError, TypeError, ValueError) as exc:
                values, used_cache = [], False
                failed.append(f"{source.get('name', 'SOURCE')}: {exc}")
            if not values:
                failed.append(str(source.get("name", "SOURCE")))
            channels.extend(values)
            cache_count += int(used_cache)
        deduplicated: dict[tuple[str, str], dict[str, str]] = {}
        for channel in channels:
            key = (str(channel.get("name", "")).casefold(), str(channel.get("url", "")))
            deduplicated[key] = channel
        self.tv_channels = sorted(
            deduplicated.values(),
            key=lambda value: (value.get("group", "OTHER"), value.get("name", "CHANNEL")),
        )
        grouped: dict[str, int] = {}
        for channel in self.tv_channels:
            group = str(channel.get("group", "OTHER")) or "OTHER"
            grouped[group] = grouped.get(group, 0) + 1
        self.tv_groups = sorted(grouped.items(), key=lambda item: item[0].casefold())
        if self.tv_channels:
            cache_note = f"  •  {cache_count} CACHED SOURCE{'S' if cache_count != 1 else ''}" if cache_count else ""
            self.status = f"{len(self.tv_channels)} TV ITEMS READY{cache_note}"
            self._open("tv-groups")
        else:
            self.status = "NO TV CHANNELS AVAILABLE; CHECK NETWORK OR SOURCES"
            if failed:
                self.tv_source_status = failed[0][:120]
            self._open("tv-sources")

    def _import_tv_sources(self) -> None:
        try:
            _sources, imported = import_sources_from_media(REMOVABLE_ROOT, TV_SOURCES_PATH)
        except OSError as exc:
            self.status = f"TV SOURCE IMPORT FAILED: {exc}"
            return
        self.status = (
            f"IMPORTED {imported} TV SOURCE{'S' if imported != 1 else ''}"
            if imported > 0 else
            "NO NEW SOURCES FOUND IN PULSEARC/TV ON USB OR SD"
        )
        self.overlay_selection = 0

    def _delete_selected_tv_source(self) -> None:
        builtins = len(BUILTIN_TV_SOURCES)
        if self.overlay_selection < builtins:
            self.status = "THE BUILT-IN FREE TV SOURCE CANNOT BE DELETED"
            return
        saved = load_saved_sources(TV_SOURCES_PATH)
        index = self.overlay_selection - builtins
        if not (0 <= index < len(saved)):
            return
        removed = str(saved[index].get("name", "TV SOURCE"))
        del saved[index]
        try:
            save_sources(TV_SOURCES_PATH, saved)
        except OSError as exc:
            self.status = f"COULD NOT DELETE SOURCE: {exc}"
            return
        self.overlay_selection = min(self.overlay_selection, max(0, self._count() - 1))
        self.status = f"REMOVED {removed.upper()}"

    def _play_tv_channel(self, channel: dict[str, str]) -> None:
        url = str(channel.get("url", ""))
        if not url:
            self.status = "CHANNEL STREAM URL IS MISSING"
            return
        name = str(channel.get("name", "TV CHANNEL"))
        short_failures = 0
        played_successfully = False
        while self.running:
            exit_requested, _return_code, elapsed = self._run_media_process(
                [
                    "/usr/bin/mpv",
                    "--fs",
                    "--no-terminal",
                    "--cache=yes",
                    "--cache-secs=10",
                    "--network-timeout=20",
                    # Most IPTV interruptions are a closed HTTP connection,
                    # not the end of the channel. Ask FFmpeg (inside MPV) to
                    # reconnect before allowing the player to exit.
                    # A normal HLS manifest ends at EOF. reconnect_at_eof can
                    # trap FFmpeg rereading that manifest before it opens the
                    # media segments, which breaks several iptv-org feeds.
                    "--demuxer-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_delay_max=10",
                    "--input-default-bindings=yes",
                    "--keep-open=no",
                    url,
                ],
                f"TUNING {name.upper()}",
                recording_channel=channel,
            )
            if exit_requested or not self.running:
                return

            # A stream that played for at least 15 seconds was valid, so a
            # later exit is treated as a transient provider/network drop and
            # receives an unlimited reconnect budget. Truly dead URLs still
            # return to the list after three quick attempts.
            if elapsed >= 15:
                played_successfully = True
                short_failures = 0
            else:
                short_failures += 1
            if not played_successfully and short_failures >= 3:
                self.status = f"{name.upper()} IS OFFLINE OR UNAVAILABLE"
                return
            self.status = f"{name.upper()} CONNECTION LOST  •  RECONNECTING"
            self._draw()
            pygame.display.flip()
            time.sleep(1.0)

    @staticmethod
    def _dvr_root() -> Path:
        preferred = Path("/var/lib/pulsearc/library/tv-recordings")
        try:
            preferred.mkdir(parents=True, exist_ok=True)
            probe = preferred / ".write-test"
            probe.write_text("ok", encoding="ascii")
            probe.unlink(missing_ok=True)
            return preferred
        except OSError:
            fallback = Path.home() / "Videos/PulseArc DVR"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

    def _dvr_recordings(self) -> list[Path]:
        root = self._dvr_root()
        return sorted(
            (path for path in root.glob("*.ts") if path.is_file() and ".part." not in path.name),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    def _toggle_selected_dvr_recording(self) -> None:
        if self.dvr_process is not None and self.dvr_process.poll() is None:
            self._stop_dvr_recording()
            return
        channels = self._tv_channels_for_group()
        if not (0 <= self.overlay_selection < len(channels)):
            return
        self._toggle_dvr_channel(channels[self.overlay_selection])

    def _toggle_dvr_channel(self, channel: dict[str, str]) -> str:
        if self.dvr_process is not None and self.dvr_process.poll() is None:
            title = self.dvr_title
            self._stop_dvr_recording()
            return f"DVR SAVED: {title}"
        name = str(channel.get("name", "TV CHANNEL"))
        url = str(channel.get("url", ""))
        if not url:
            self.status = "DVR COULD NOT START: STREAM URL IS MISSING"
            return self.status
        safe = re.sub(r"[^A-Za-z0-9._ -]+", "", name).strip()[:80] or "TV Recording"
        stamp = time.strftime("%Y-%m-%d %H-%M-%S")
        partial = self._dvr_root() / f"{safe} - {stamp}.part.ts"
        try:
            self.dvr_process = subprocess.Popen(
                [
                    "/usr/bin/ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", url, "-map", "0", "-c", "copy", "-f", "mpegts", str(partial),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self.dvr_process = None
            self.status = f"DVR COULD NOT START: {exc}"
            return self.status
        self.dvr_title = name
        self.dvr_partial_path = partial
        self.status = f"DVR RECORDING {name.upper()}  |  PRESS RB/R1 TO STOP"
        return f"DVR RECORDING STARTED: {name}  |  RB/R1 TO STOP"

    def _stop_dvr_recording(self, silent: bool = False) -> None:
        process = self.dvr_process
        partial = self.dvr_partial_path
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        final: Path | None = None
        if partial is not None and partial.is_file() and partial.stat().st_size > 0:
            final = partial.with_name(partial.name.replace(".part.ts", ".ts"))
            partial.replace(final)
        elif partial is not None:
            partial.unlink(missing_ok=True)
        title = self.dvr_title
        self.dvr_process = None
        self.dvr_partial_path = None
        self.dvr_title = ""
        if not silent:
            self.status = f"DVR SAVED {final.name}" if final is not None else f"DVR RECORDING FAILED: {title}"

    def _play_dvr_recording(self, path: Path) -> None:
        self._run_media_process(
            ["/usr/bin/mpv", "--fs", "--no-terminal", "--input-default-bindings=yes", str(path)],
            f"PLAYING DVR  •  {path.stem.upper()}",
        )

    def _delete_selected_dvr_recording(self) -> None:
        recordings = self._dvr_recordings()
        if not (0 <= self.overlay_selection < len(recordings)):
            return
        name = recordings[self.overlay_selection].name
        try:
            recordings[self.overlay_selection].unlink()
        except OSError as exc:
            self.status = f"DVR DELETE FAILED: {exc}"
            return
        self.overlay_selection = min(self.overlay_selection, max(0, len(self._dvr_recordings())))
        self.status = f"DELETED {name.upper()}"

    @staticmethod
    def _screen_record_root() -> Path:
        preferred = Path("/var/lib/pulsearc/library/screen-recordings")
        try:
            preferred.mkdir(parents=True, exist_ok=True)
            probe = preferred / ".write-test"
            probe.write_text("ok", encoding="ascii")
            probe.unlink(missing_ok=True)
            return preferred
        except OSError:
            fallback = Path.home() / "Videos/PulseArc Recordings"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

    def _toggle_screen_recording(self) -> None:
        if self.screen_record_process is not None and self.screen_record_process.poll() is None:
            self._stop_screen_recording()
            return
        desktop = pygame.display.get_desktop_sizes()[0] if pygame.display.get_desktop_sizes() else LOGICAL_SIZE
        display = os.environ.get("DISPLAY", ":0")
        stamp = time.strftime("%Y-%m-%d %H-%M-%S")
        partial = self._screen_record_root() / f"PulseArc - {stamp}.part.mp4"
        sink = ""
        try:
            sink = subprocess.run(
                ["/usr/bin/pactl", "get-default-sink"],
                check=False,
                capture_output=True,
                text=True,
                timeout=1.5,
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
        command = [
            "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-thread_queue_size", "1024", "-f", "x11grab", "-draw_mouse", "1",
            "-framerate", "30", "-video_size", f"{desktop[0]}x{desktop[1]}", "-i", f"{display}.0",
        ]
        if sink:
            command.extend(["-thread_queue_size", "1024", "-f", "pulse", "-i", f"{sink}.monitor"])
        command.extend([
            "-vf", "scale=w=min(1920\\,iw):h=-2",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p",
        ])
        if sink:
            command.extend(["-c:a", "aac", "-b:a", "160k"])
        command.extend(["-movflags", "+faststart", str(partial)])
        try:
            self.screen_record_process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self.screen_record_process = None
            self.status = f"SCREEN RECORDER COULD NOT START: {exc}"
            return
        self.screen_record_partial_path = partial
        self.status = "SCREEN RECORDING STARTED  •  EXTRAS TO STOP & SAVE"

    def _stop_screen_recording(self, silent: bool = False) -> None:
        process = self.screen_record_process
        partial = self.screen_record_partial_path
        if process is not None and process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.write(b"q\n")
                    process.stdin.flush()
                process.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        final: Path | None = None
        if partial is not None and partial.is_file() and partial.stat().st_size > 0:
            final = partial.with_name(partial.name.replace(".part.mp4", ".mp4"))
            partial.replace(final)
        elif partial is not None:
            partial.unlink(missing_ok=True)
        self.screen_record_process = None
        self.screen_record_partial_path = None
        if not silent:
            self.status = f"SCREEN RECORDING SAVED  •  {final.name}" if final is not None else "SCREEN RECORDING FAILED"

    @staticmethod
    def _browser_executable() -> str:
        candidates = (
            "/usr/bin/firefox",
            str(Path.home() / ".local/share/pulsearc/apps/firefox/firefox/firefox"),
            "/usr/bin/chromium",
        )
        return next((path for path in candidates if Path(path).is_file() and os.access(path, os.X_OK)), "")

    def _apps_action(self, index: int) -> None:
        if index == 0:
            launchers = (
                Path("/usr/local/bin/pulsearc-steam"),
                Path.home() / ".local/bin/pulsearc-steam",
            )
            steam = next((path for path in launchers if path.is_file() and os.access(path, os.X_OK)), None)
            if steam is None:
                self.status = "STEAM IS NOT INSTALLED"
                return
            try:
                process = subprocess.Popen([str(steam)], start_new_session=True)
                time.sleep(0.35)
                if process.poll() is not None:
                    self.status = f"STEAM FAILED TO START (EXIT {process.returncode}); SEE ~/.cache/pulsearc/logs/steam.log"
                    return
                self.status = "STEAM BIG PICTURE STARTED  •  USE STEAM'S EXIT MENU TO RETURN"
                self.status = "STEAM BIG PICTURE STARTED  •  SIGN IN TO ACCESS, INSTALL, AND RUN OWNED GAMES"
                self._maximize_external_window(("steam",))
                self._pause_theme_animation()
                try:
                    process.wait()
                finally:
                    self._resume_theme_animation()
                pygame.event.clear()
                self.status = "STEAM CLOSED"
            except OSError as exc:
                self.status = f"STEAM FAILED: {exc}"
        elif index == 1:
            self._launch_heroic()
        elif index == 2:
            self._launch_streaming_app({"name": "Xbox Cloud Gaming", "url": "https://www.xbox.com/en-US/play"})
        elif index == 3:
            self._launch_geforce_now()
        elif index == 4:
            self._launch_playstation_plus()
        elif index == 5:
            self._launch_streaming_app({"name": "Web Browser", "url": "https://vimm.net/vault", "normal_browser": "1"})
        elif index == 6:
            self._open("downloads")
        else:
            self._back()

    def _launch_heroic(self) -> None:
        candidates = (
            Path.home() / ".local/share/pulsearc/apps/heroic/Heroic.AppImage",
            Path("/usr/lib/pulsearc/apps/heroic/Heroic.AppImage"),
        )
        executable = next((path for path in candidates if path.is_file()), None)
        if executable is None:
            command = shutil.which("heroic")
            if command:
                executable = Path(command)
        if executable is None:
            self.status = "HEROIC IS NOT INSTALLED; EPIC AND GOG REQUIRE THE FULL PULSEARC IMAGE"
            return
        environment = dict(os.environ)
        environment["APPIMAGE_EXTRACT_AND_RUN"] = "1"
        environment.setdefault("HEROIC_DEFAULT_INSTALL_PATH", str(Path.home() / "Games/Heroic"))
        (Path.home() / "Games/Heroic").mkdir(parents=True, exist_ok=True)
        log_root = Path.home() / ".cache/pulsearc/logs"
        log_root.mkdir(parents=True, exist_ok=True)
        try:
            with (log_root / "heroic.log").open("ab") as log:
                process = subprocess.Popen(
                    [str(executable), "--start-maximized"],
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            time.sleep(0.35)
            if process.poll() is not None:
                self.status = f"HEROIC FAILED TO START (EXIT {process.returncode}); SEE ~/.cache/pulsearc/logs/heroic.log"
                return
            # Heroic has its own controller-first navigation.  Keep the
            # PulseArc menu paused while Heroic owns focus so one button press
            # cannot operate both interfaces at the same time.
            window_classes = ("heroic", "Heroic Games Launcher")
            self._maximize_external_window(window_classes)
            self.status = "HEROIC STARTED  â€¢  EPIC + GOG + AMAZON LIBRARIES"
            self.status = "HEROIC STARTED  •  SIGN IN TO ACCESS, INSTALL, AND RUN EPIC + GOG GAMES"
            self._wait_for_external_app(process, window_classes, controller_navigation=True)
            self.status = "HEROIC CLOSED"
        except OSError as exc:
            self.status = f"HEROIC FAILED: {exc}"

    @staticmethod
    def _maximize_external_window(window_classes: tuple[str, ...]) -> None:
        """Focus and size the largest matching X11 window to the display."""
        xdotool = PulseArcUI._xdotool_executable()
        if not xdotool:
            return

        def maximize() -> None:
            environment = PulseArcUI._xdotool_environment()
            for _ in range(120):
                candidates: list[tuple[int, str]] = []
                for window_id in PulseArcUI._external_window_ids(window_classes, environment):
                    geometry = PulseArcUI._window_geometry(window_id, environment)
                    if geometry is None:
                        continue
                    width, height = geometry
                    if width >= 320 and height >= 200:
                        candidates.append((width * height, window_id))
                if candidates:
                    window_id = max(candidates)[1]
                    try:
                        display = subprocess.run(
                            [xdotool, "getdisplaygeometry"], check=False,
                            capture_output=True, text=True, timeout=1.0, env=environment,
                        ).stdout.split()
                        width, height = display[:2] if len(display) >= 2 else ("1920", "1080")
                        subprocess.run(
                            [xdotool, "windowmap", window_id, "windowmove", window_id, "0", "0",
                             "windowsize", window_id, width, height,
                             "windowactivate", "--sync", window_id],
                            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=1.5, env=environment,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                time.sleep(0.25)

        threading.Thread(target=maximize, daemon=True).start()

    @staticmethod
    def _xdotool_environment() -> dict[str, str]:
        environment = dict(os.environ)
        local_lib = str(Path.home() / ".local/lib")
        environment["LD_LIBRARY_PATH"] = (
            local_lib + (":" + environment["LD_LIBRARY_PATH"] if environment.get("LD_LIBRARY_PATH") else "")
        )
        return environment

    @staticmethod
    def _external_window_ids(
        window_classes: tuple[str, ...], environment: dict[str, str] | None = None,
    ) -> list[str]:
        xdotool = PulseArcUI._xdotool_executable()
        if not xdotool:
            return []
        found: list[str] = []
        for window_class in window_classes:
            try:
                result = subprocess.run(
                    [xdotool, "search", "--onlyvisible", "--class", window_class],
                    check=False, capture_output=True, text=True, timeout=0.7,
                    env=environment or PulseArcUI._xdotool_environment(),
                )
                for window_id in result.stdout.splitlines():
                    window_id = window_id.strip()
                    if window_id and window_id not in found:
                        found.append(window_id)
            except (OSError, subprocess.TimeoutExpired):
                continue
        return found

    @staticmethod
    def _window_geometry(
        window_id: str, environment: dict[str, str] | None = None,
    ) -> tuple[int, int] | None:
        xdotool = PulseArcUI._xdotool_executable()
        if not xdotool:
            return None
        try:
            result = subprocess.run(
                [xdotool, "getwindowgeometry", "--shell", window_id],
                check=False, capture_output=True, text=True, timeout=0.7,
                env=environment or PulseArcUI._xdotool_environment(),
            )
            values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            return int(values["WIDTH"]), int(values["HEIGHT"])
        except (KeyError, ValueError, OSError, subprocess.TimeoutExpired):
            return None

    def _active_external_window_matches(self, window_classes: tuple[str, ...]) -> bool:
        xdotool = self._xdotool_executable()
        if not xdotool:
            return False
        environment = self._xdotool_environment()
        try:
            active = subprocess.run(
                [xdotool, "getactivewindow"], check=False, capture_output=True,
                text=True, timeout=0.5, env=environment,
            ).stdout.strip()
            if not active:
                return False
            window_class = subprocess.run(
                [xdotool, "getwindowclassname", active], check=False,
                capture_output=True, text=True, timeout=0.5, env=environment,
            ).stdout
            window_name = subprocess.run(
                [xdotool, "getwindowname", active], check=False,
                capture_output=True, text=True, timeout=0.5, env=environment,
            ).stdout
            identity = f"{window_class} {window_name}".lower()
            return any(value.lower() in identity for value in window_classes)
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _send_external_key(self, key: str) -> None:
        xdotool = self._xdotool_executable()
        if not xdotool:
            return
        try:
            subprocess.run(
                [xdotool, "key", "--clearmodifiers", key], check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=0.5,
                env=self._xdotool_environment(),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _close_external_app(
        self, process: subprocess.Popen[Any], window_classes: tuple[str, ...],
    ) -> None:
        xdotool = self._xdotool_executable()
        environment = self._xdotool_environment()
        if xdotool:
            for window_id in self._external_window_ids(window_classes, environment):
                try:
                    subprocess.run(
                        [xdotool, "key", "--window", window_id, "--clearmodifiers", "alt+F4"],
                        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=0.7, env=environment,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass
        try:
            os.killpg(process.pid, 15)
            process.wait(timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, 9)
            except OSError:
                pass

    def _wait_for_external_app(
        self,
        process: subprocess.Popen[Any],
        window_classes: tuple[str, ...],
        *,
        controller_navigation: bool = False,
    ) -> int:
        self._pause_theme_animation()
        try:
            return self._wait_for_external_app_unpaused(
                process,
                window_classes,
                controller_navigation=controller_navigation,
            )
        finally:
            self._resume_theme_animation()

    def _wait_for_external_app_unpaused(
        self,
        process: subprocess.Popen[Any],
        window_classes: tuple[str, ...],
        *,
        controller_navigation: bool = False,
    ) -> int:
        """Own controller events until an external app and its windows close."""
        axis_latch = {0: 0, 1: 0}
        started = time.monotonic()
        saw_window = False
        window_missing_since: float | None = None
        next_window_scan = 0.0
        windows: list[str] = []
        exit_requested = False
        while True:
            now = time.monotonic()
            if now >= next_window_scan:
                windows = self._external_window_ids(window_classes)
                next_window_scan = now + 0.20
                if windows:
                    saw_window = True
                    window_missing_since = None
                elif saw_window:
                    window_missing_since = window_missing_since or now

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                    exit_requested = True
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    exit_requested = True
                elif event.type == pygame.JOYBUTTONDOWN:
                    if event.button == 6:
                        self.view_down = True
                    elif event.button == 7:
                        self.menu_down = True
                    elif controller_navigation and self._active_external_window_matches(window_classes):
                        if event.button == 0:
                            self._send_external_key("Return")
                        elif event.button == 1:
                            self._send_external_key("Escape")
                    if self.view_down and self.menu_down:
                        exit_requested = True
                elif event.type == pygame.JOYBUTTONUP:
                    if event.button == 6:
                        self.view_down = False
                    elif event.button == 7:
                        self.menu_down = False
                elif controller_navigation and self._active_external_window_matches(window_classes):
                    if event.type == pygame.JOYHATMOTION:
                        if event.value[0]:
                            self._send_external_key("Right" if event.value[0] > 0 else "Left")
                        if event.value[1]:
                            self._send_external_key("Up" if event.value[1] > 0 else "Down")
                    elif event.type == pygame.JOYAXISMOTION and event.axis in axis_latch:
                        direction = 1 if event.value > 0.55 else -1 if event.value < -0.55 else 0
                        if direction and axis_latch[event.axis] != direction:
                            key = (
                                ("Right" if direction > 0 else "Left")
                                if event.axis == 0 else
                                ("Down" if direction > 0 else "Up")
                            )
                            self._send_external_key(key)
                        axis_latch[event.axis] = direction

            if exit_requested:
                self._close_external_app(process, window_classes)
                break

            process_done = process.poll() is not None
            startup_expired = time.monotonic() - started >= 15.0
            windows_gone = (
                saw_window and window_missing_since is not None and
                time.monotonic() - window_missing_since >= 3.0
            )
            if windows_gone:
                if not process_done:
                    self._close_external_app(process, window_classes)
                break
            if process_done and not saw_window and startup_expired:
                break
            time.sleep(0.02)

        self.view_down = False
        self.menu_down = False
        pygame.event.clear()
        return int(process.returncode or 0)

    def _launch_geforce_now(self) -> None:
        native = shutil.which("geforcenow")
        if native:
            try:
                process = subprocess.Popen([native], start_new_session=True)
                self.status = "GEFORCE NOW LINUX BETA STARTED"
                self._maximize_external_window(("geforcenow", "GeForce NOW"))
                self._pause_theme_animation()
                try:
                    process.wait()
                finally:
                    self._resume_theme_animation()
                pygame.event.clear()
                self.status = "GEFORCE NOW CLOSED"
                return
            except OSError:
                pass
        flatpak = shutil.which("flatpak")
        if flatpak:
            installed = subprocess.run(
                [flatpak, "info", "com.nvidia.geforcenow"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).returncode == 0
            if installed:
                process = subprocess.Popen([flatpak, "run", "com.nvidia.geforcenow"], start_new_session=True)
                self.status = "GEFORCE NOW LINUX BETA STARTED"
                self._maximize_external_window(("geforcenow", "GeForce NOW"))
                self._pause_theme_animation()
                try:
                    process.wait()
                finally:
                    self._resume_theme_animation()
                pygame.event.clear()
                self.status = "GEFORCE NOW CLOSED"
                return
        self.status = "NATIVE GEFORCE NOW IS NOT INSTALLED; USING THE WEB FALLBACK"
        self._launch_streaming_app({"name": "GeForce NOW", "url": "https://play.geforcenow.com/"})

    def _launch_playstation_plus(self) -> None:
        launchers = (
            Path("/usr/local/bin/pulsearc-playstation-plus-cloud"),
            Path.home() / ".local/bin/pulsearc-playstation-plus-cloud",
            Path.home() / ".local/share/pulsearc/apps/playstation-plus/run",
            Path.home() / ".local/bin/pulsearc-playstation-plus",
        )
        launcher = next((path for path in launchers if path.is_file() and os.access(path, os.X_OK)), None)
        if launcher is None:
            self.status = "PLAYSTATION PLUS CLOUD CLIENT IS NOT INSTALLED; REMOTE PLAY IS NOT INCLUDED"
            return
        try:
            process = subprocess.Popen([str(launcher)], start_new_session=True)
            self.status = "PLAYSTATION PLUS STARTED  â€¢  VIEW + MENU TO EXIT"
            window_classes = ("pspluslauncher.exe", "agl.exe", "PlayStation")
            self._maximize_external_window(window_classes)
            returncode = self._wait_for_external_app(process, window_classes)
            self.status = (
                "PLAYSTATION PLUS CLOSED"
                if returncode == 0 else
                f"PLAYSTATION PLUS FAILED (EXIT {returncode}); SEE ~/.local/share/pulsearc/apps/playstation-plus-cloud/logs/launch.log"
            )
        except OSError as exc:
            self.status = f"PLAYSTATION PLUS CLOUD CLIENT FAILED: {exc}"

    @staticmethod
    def _archive_roots() -> tuple[Path, ...]:
        roots = [DOWNLOADS_ROOT]
        if REMOVABLE_ROOT.is_dir():
            roots.append(REMOVABLE_ROOT)
        return tuple(path for path in roots if path.is_dir())

    def _refresh_download_archives(self) -> None:
        self.status = "SCANNING DOWNLOADS, USB, AND SD FOR ZIP / 7Z / RAR GAME ARCHIVES"
        try:
            self.download_archives = discover_archives(self._archive_roots())
            self.status = f"FOUND {len(self.download_archives)} SAFE ARCHIVE CANDIDATES"
        except OSError as exc:
            self.download_archives = []
            self.status = f"ARCHIVE SCAN FAILED: {exc}"
        self.overlay_selection = 0

    def _start_archive_install(self, item: ArchiveItem) -> None:
        if self.install_thread is not None and self.install_thread.is_alive():
            self.status = "AN INSTALL IS ALREADY RUNNING"
            return
        self.install_title = item.path.stem
        self.install_total = max(1, item.size)
        self.install_bytes = 0
        self.install_progress = 0.0
        self.install_started = time.monotonic()
        self.install_phase = "VALIDATING ARCHIVE"
        self.install_result = ""
        self.install_return_screen = "downloads"
        self._open("install-progress")
        self.install_thread = threading.Thread(
            target=self._archive_install_worker,
            args=(item,),
            daemon=True,
            name="pulsearc-archive-install",
        )
        self.install_thread.start()

    def _archive_install_worker(self, item: ArchiveItem) -> None:
        destination: Path | None = None
        try:
            self.install_progress = 0.10
            self.install_phase = "EXTRACTING TO ISOLATED STAGING"
            destination = install_archive(item.path, self._archive_roots(), IMPORTED_GAMES_ROOT)
            self.install_progress = 0.72
            self.install_phase = "VERIFYING GAME CONTENT"
            for path in reversed(PULSEARC_CORE_PATHS):
                value = str(path)
                if path.is_dir() and value not in sys.path:
                    sys.path.insert(0, value)
            from pulsearc.scanner import scan
            entries = scan(destination)
            if not entries:
                shutil.rmtree(destination)
                destination = None
                raise ValueError("no supported games were found after extraction")
            self.install_phase = "REGISTERING LIBRARY"
            if not self._rebuild_internal_library_index():
                raise ValueError("library registration failed")
            self.install_progress = 1.0
            self.install_bytes = self.install_total
            self.install_result = "installed"
            self.install_phase = "COMPLETE"
            self.status = f"INSTALLED {len(entries)} GAME{'S' if len(entries) != 1 else ''} FROM {item.path.name.upper()}"
        except (ImportError, OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            if destination is not None and destination.is_dir():
                try:
                    destination.resolve().relative_to(IMPORTED_GAMES_ROOT.resolve())
                    shutil.rmtree(destination)
                except (OSError, ValueError):
                    pass
            self.install_result = "failed"
            self.install_phase = "FAILED"
            self.status = f"INSTALL FAILED: {exc}"

    def _launch_streaming_app(self, app: dict[str, str]) -> None:
        browser = self._browser_executable()
        if not browser:
            self.status = "TV WEB APPS REQUIRE THE FIREFOX PACKAGE"
            return
        name = str(app.get("name", "TV APP"))
        url = str(app.get("url", ""))
        normal_browser = str(app.get("normal_browser", "")) == "1"
        profile = TV_DATA_ROOT / "firefox-profile"
        profile.mkdir(parents=True, exist_ok=True)
        preferences = profile / "user.js"
        if not preferences.exists():
            preferences.write_text(
                'user_pref("browser.aboutwelcome.enabled", false);\n'
                'user_pref("browser.shell.checkDefaultBrowser", false);\n'
                'user_pref("datareporting.policy.dataSubmissionEnabled", false);\n'
                'user_pref("browser.safebrowsing.malware.enabled", true);\n'
                'user_pref("browser.safebrowsing.phishing.enabled", true);\n'
                'user_pref("dom.disable_open_during_load", true);\n'
                'user_pref("dom.security.https_only_mode", true);\n'
                'user_pref("privacy.trackingprotection.enabled", true);\n'
                'user_pref("privacy.trackingprotection.socialtracking.enabled", true);\n'
                'user_pref("media.eme.enabled", true);\n'
                'user_pref("media.gmp-widevinecdm.enabled", true);\n',
                encoding="utf-8",
            )
        try:
            with preferences.open("a", encoding="utf-8") as output:
                output.write(
                    'user_pref("browser.startup.page", 1);\n'
                    'user_pref("browser.startup.homepage", "https://vimm.net/vault");\n'
                    'user_pref("browser.safebrowsing.malware.enabled", true);\n'
                    'user_pref("browser.safebrowsing.phishing.enabled", true);\n'
                    'user_pref("dom.disable_open_during_load", true);\n'
                    'user_pref("dom.security.https_only_mode", true);\n'
                    'user_pref("privacy.trackingprotection.enabled", true);\n'
                )
        except OSError:
            pass
        if Path(browser).name == "firefox":
            command = [browser, "--new-instance", "--no-remote", "--profile", str(profile), url]
            if not normal_browser:
                command.insert(1, "--kiosk")
        elif normal_browser:
            command = [browser, "--new-window", url, f"--user-data-dir={TV_DATA_ROOT / 'chromium-profile'}"]
        else:
            command = [browser, "--kiosk", f"--app={url}", f"--user-data-dir={TV_DATA_ROOT / 'chromium-profile'}"]
        self.status = f"OPENING {name}  •  VIEW + MENU TO EXIT"
        self._draw()
        pygame.display.flip()
        process: subprocess.Popen[Any] | None = None
        self._pause_theme_animation()
        try:
            process = subprocess.Popen(command, start_new_session=True)
            self._maximize_external_window(("firefox", "chromium", "google-chrome"))
            axis_latch = {0: 0, 1: 0, 2: 0, 3: 0}
            while process.poll() is None:
                exit_requested = False
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                        exit_requested = True
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        exit_requested = True
                    elif event.type == pygame.JOYBUTTONDOWN:
                        if event.button == 0:
                            self._browser_key("click 1")
                        elif event.button == 1:
                            self._browser_key("key alt+Left")
                        elif event.button == 4:
                            self._browser_key("key Page_Up")
                        elif event.button == 5:
                            self._browser_key("key Page_Down")
                        elif event.button == 6:
                            self.view_down = True
                        elif event.button == 7:
                            self.menu_down = True
                        if self.view_down and self.menu_down:
                            exit_requested = True
                    elif event.type == pygame.JOYBUTTONUP:
                        if event.button == 6:
                            self.view_down = False
                        elif event.button == 7:
                            self.menu_down = False
                    elif event.type == pygame.JOYHATMOTION:
                        if event.value[0]:
                            self._browser_key("key Right" if event.value[0] > 0 else "key Left")
                        if event.value[1]:
                            self._browser_key("key Up" if event.value[1] > 0 else "key Down")
                    elif event.type == pygame.JOYAXISMOTION and event.axis in axis_latch:
                        direction = 1 if event.value > 0.35 else -1 if event.value < -0.35 else 0
                        if event.axis in (2, 3) and direction:
                            dx = int(event.value * 22) if event.axis == 2 else 0
                            dy = int(event.value * 22) if event.axis == 3 else 0
                            self._browser_key(f"mousemove_relative -- {dx} {dy}")
                        elif event.axis in (0, 1) and direction and axis_latch[event.axis] != direction:
                            key = ("Right" if direction > 0 else "Left") if event.axis == 0 else ("Down" if direction > 0 else "Up")
                            self._browser_key(f"key {key}")
                        axis_latch[event.axis] = direction
                    if exit_requested:
                        break
                if exit_requested:
                    break
                time.sleep(0.02)
        except OSError as exc:
            self.status = f"{name} FAILED: {exc}"
        finally:
            if process is not None and process.poll() is None:
                try:
                    os.killpg(process.pid, 15)
                    process.wait(timeout=4)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(process.pid, 9)
                    except OSError:
                        pass
            self.view_down = False
            self.menu_down = False
            self.status = f"{name} CLOSED"
            self._resume_theme_animation()

    def _browser_key(self, command: str) -> None:
        try:
            subprocess.run(
                [self._xdotool_executable(), *command.split()],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=0.4,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    @staticmethod
    def _projectm_executable() -> str:
        return next(
            (
                path
                for path in (
                    str(Path.home() / ".local/bin/pulsearc-projectm"),
                    "/usr/bin/projectM-pulseaudio",
                    "/usr/bin/projectMSDL",
                )
                if Path(path).is_file()
            ),
            "",
        )

    @staticmethod
    def _xdotool_executable() -> str:
        candidates = [
            Path.home() / ".local/bin/pulsearc-xdotool",
            Path.home() / ".local/bin/xdotool",
        ]
        system = shutil.which("xdotool")
        if system:
            candidates.append(Path(system))
        candidates.append(Path("/usr/bin/xdotool"))
        executable = next(
            (path for path in candidates if path.is_file() and os.access(path, os.X_OK)),
            None,
        )
        return str(executable) if executable else ""

    def _start_projectm_visualizer(self) -> subprocess.Popen[Any] | None:
        executable = self._projectm_executable()
        if not executable:
            self.status = "PROJECTM IS NOT INSTALLED"
            return None
        try:
            self._prepare_projectm_presets()
            process = subprocess.Popen([executable])
            # The packaged frontend may ignore its Fullscreen setting on the
            # first run. Wait for the actual X11 window, then request
            # fullscreen explicitly instead of racing it with a fixed delay.
            deadline = time.monotonic() + 4.0
            while process.poll() is None and time.monotonic() < deadline:
                window = subprocess.run(
                    [self._xdotool_executable(), "search", "--onlyvisible", "--name", "projectM"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=0.5,
                ).stdout.splitlines()
                if window:
                    subprocess.run(
                        [
                            self._xdotool_executable(), "key", "--window", window[-1].strip(),
                            "--clearmodifiers", "f",
                        ],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=1.0,
                    )
                    break
                time.sleep(0.1)
            return process
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.status = f"PROJECTM FAILED: {exc}"
            return None

    def _prepare_projectm_presets(self) -> None:
        """Expose every unique preset and make random playback explicit."""
        bundled = Path.home() / ".local/share/pulsearc/runners/projectm/root/usr/share/projectM/presets"
        source = bundled if bundled.is_dir() else Path("/usr/share/projectM/presets")
        if not source.is_dir():
            return
        presets = sorted(path for path in source.rglob("*.milk") if path.is_file())
        unique_root = Path.home() / ".cache/pulsearc/projectm-presets-unique"
        marker = unique_root / ".source-state"
        state = f"{source.resolve()}|{len(presets)}|{sum(path.stat().st_size for path in presets)}"
        if read_json(marker, "") != state:
            staging = unique_root.with_name(unique_root.name + ".new")
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)
            seen: set[str] = set()
            for preset in presets:
                digest = hashlib.sha256(preset.read_bytes()).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                (staging / f"{digest}.milk").symlink_to(preset.resolve())
            marker_path = staging / ".source-state"
            marker_path.write_text(json.dumps(state), encoding="utf-8")
            old = unique_root.with_name(unique_root.name + ".old")
            shutil.rmtree(old, ignore_errors=True)
            if unique_root.exists():
                unique_root.replace(old)
            staging.replace(unique_root)
            shutil.rmtree(old, ignore_errors=True)
        config_path = Path.home() / ".projectM/config.inp"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            lines = config_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        replacements = {
            "Preset Path": str(unique_root),
            "Shuffle Enabled": "true",
            "Preset Duration": "20",
        }
        output: list[str] = []
        replaced: set[str] = set()
        for line in lines:
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            if key in replacements:
                output.append(f"{key} = {replacements[key]}")
                replaced.add(key)
            else:
                output.append(line)
        for key, value in replacements.items():
            if key not in replaced:
                output.append(f"{key} = {value}")
        config_path.write_text("\n".join(output) + "\n", encoding="utf-8")

    def _launch_projectm(self) -> None:
        process = self._start_projectm_visualizer()
        if process is None:
            self._back()
            return
        self._pause_theme_animation()
        try:
            exit_requested = False
            while process.poll() is None:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self.running = False
                        exit_requested = True
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        exit_requested = True
                    elif event.type == pygame.JOYBUTTONDOWN:
                        if event.button == 1:
                            exit_requested = True
                        elif event.button == 6:
                            self.view_down = True
                        elif event.button == 7:
                            self.menu_down = True
                        if self.view_down and self.menu_down:
                            exit_requested = True
                    elif event.type == pygame.JOYBUTTONUP:
                        if event.button == 6:
                            self.view_down = False
                        elif event.button == 7:
                            self.menu_down = False
                if exit_requested:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2)
                    break
                time.sleep(0.02)
            self.status = "PROJECTM CLOSED"
        except OSError as exc:
            self.status = f"PROJECTM FAILED: {exc}"
        finally:
            self.view_down = False
            self.menu_down = False
            self._resume_theme_animation()

    def _store_layout(self) -> tuple[set[tuple[int, int]], list[tuple[float, float, int]], int, int]:
        entries = self._store_entries()
        shelf_count = max(1, math.ceil(max(1, len(entries)) / 24))
        width, height = 20, 8 + shelf_count * 4
        walls: set[tuple[int, int]] = set()
        for x in range(width):
            walls.add((x, 0))
            walls.add((x, height - 1))
        for y in range(height):
            walls.add((0, y))
            walls.add((width - 1, y))
        cases: list[tuple[float, float, int]] = []
        entry_index = 0
        for shelf in range(shelf_count):
            shelf_y = 5 + shelf * 4
            for x in range(3, 17):
                walls.add((x, shelf_y))
            for side_y in (shelf_y - 0.56, shelf_y + 1.56):
                for slot in range(12):
                    if entry_index >= len(entries):
                        break
                    cases.append((3.25 + slot * 1.12, side_y, entry_index))
                    entry_index += 1
        return walls, cases, width, height

    @staticmethod
    def _store_wall_kind(map_x: int, map_y: int, map_width: int, map_height: int) -> str:
        """Classify a ray hit so shelves and the entrance get distinct materials."""
        if map_y == 0 and 8 <= map_x <= 11:
            return "entrance"
        if map_x in (0, map_width - 1) or map_y in (0, map_height - 1):
            return "wall"
        return "shelf"

    @staticmethod
    def _store_project(
        world_x: float,
        world_y: float,
        player: list[float],
        angle: float,
        width: int,
        height: int,
        fov: float,
    ) -> tuple[int, int, float] | None:
        dx, dy = world_x - player[0], world_y - player[1]
        distance = math.hypot(dx, dy)
        relative = PulseArcUI._angle_delta(math.atan2(dy, dx) - angle)
        depth = distance * math.cos(relative)
        if depth <= 0.08 or abs(relative) > fov * 0.62:
            return None
        return int((0.5 + relative / fov) * width), height // 2, depth

    def _store_clear(self, x: float, y: float) -> bool:
        walls, _cases, width, height = self._store_layout()
        if x < 0.35 or y < 0.35 or x > width - 0.35 or y > height - 0.35:
            return False
        radius = 0.25
        for px, py in ((x - radius, y - radius), (x + radius, y - radius),
                       (x - radius, y + radius), (x + radius, y + radius)):
            if (int(px), int(py)) in walls:
                return False
        return True

    def _store_step(self, distance: float) -> None:
        next_x = self.store_player[0] + math.cos(self.store_angle) * distance
        next_y = self.store_player[1] + math.sin(self.store_angle) * distance
        if self._store_clear(next_x, self.store_player[1]):
            self.store_player[0] = next_x
        if self._store_clear(self.store_player[0], next_y):
            self.store_player[1] = next_y

    def _store_strafe(self, distance: float) -> None:
        next_x = self.store_player[0] + math.cos(self.store_angle + math.pi / 2) * distance
        next_y = self.store_player[1] + math.sin(self.store_angle + math.pi / 2) * distance
        if self._store_clear(next_x, self.store_player[1]):
            self.store_player[0] = next_x
        if self._store_clear(self.store_player[0], next_y):
            self.store_player[1] = next_y

    def _update_3d_store(self, elapsed: float) -> None:
        if elapsed <= 0:
            return
        if self.screen_name == "3d-details":
            rotate = self.store_axes.get(2, 0.0)
            if abs(rotate) > 0.16:
                self.store_case_angle = (self.store_case_angle + rotate * 2.1 * elapsed) % math.tau
            return
        if self.screen_name != "3d-library":
            return
        strafe = self.store_axes.get(0, 0.0)
        forward = -self.store_axes.get(1, 0.0)
        turn = self.store_axes.get(2, 0.0)
        if abs(turn) > 0.16:
            self.store_angle = (self.store_angle + turn * 2.15 * elapsed) % math.tau
        if abs(forward) > 0.16:
            self._store_step(forward * 2.8 * elapsed)
        if abs(strafe) > 0.16:
            self._store_strafe(strafe * 2.25 * elapsed)

    @staticmethod
    def _angle_delta(value: float) -> float:
        return (value + math.pi) % math.tau - math.pi

    def _store_focus(self, cases: list[tuple[float, float, int]]) -> int | None:
        best: tuple[float, int] | None = None
        for x, y, index in cases:
            dx, dy = x - self.store_player[0], y - self.store_player[1]
            distance = math.hypot(dx, dy)
            delta = abs(self._angle_delta(math.atan2(dy, dx) - self.store_angle))
            if distance <= 3.2 and delta <= 0.18:
                score = delta * 5.0 + distance * 0.08
                if best is None or score < best[0]:
                    best = (score, index)
        return best[1] if best else None

    def _store_cycle_case(self, amount: int) -> bool:
        """Cycle cases on the nearest shelf face and turn toward the choice."""
        _walls, cases, _width, _height = self._store_layout()
        nearby = [
            case for case in cases
            if math.hypot(case[0] - self.store_player[0], case[1] - self.store_player[1]) <= 3.2
        ]
        if not nearby:
            return False
        nearest_y = min(nearby, key=lambda case: abs(case[1] - self.store_player[1]))[1]
        row = sorted((case for case in nearby if abs(case[1] - nearest_y) < 0.12), key=lambda case: case[0])
        if not row:
            return False
        current = 0
        if self.store_focus_index is not None:
            current = next((index for index, case in enumerate(row) if case[2] == self.store_focus_index), 0)
        else:
            current = min(
                range(len(row)),
                key=lambda index: math.hypot(row[index][0] - self.store_player[0], row[index][1] - self.store_player[1]),
            )
        selected = row[(current + amount) % len(row)]
        self.store_focus_index = selected[2]
        self.store_angle = math.atan2(selected[1] - self.store_player[1], selected[0] - self.store_player[0]) % math.tau
        return True

    def _draw_3d_store(self) -> None:
        view = self.store_view
        width, height = view.get_size()
        horizon = height // 2
        # Bright drop ceiling and blue patterned carpet establish the look of
        # a late-1990s video-rental shop before any cases enter the view.
        for y in range(horizon):
            shade = 68 + int(72 * y / max(1, horizon))
            pygame.draw.line(view, (shade, shade + 5, shade + 10), (0, y), (width, y))
        for y in range(horizon, height):
            depth = (y - horizon) / max(1, height - horizon)
            stripe = 8 if int(depth * 16) % 2 else 0
            pygame.draw.line(view, (19 + stripe, 37 + stripe, 78 + int(depth * 24)), (0, y), (width, y))
        for line_y in (18, 43, 72, 101, 122):
            pygame.draw.line(view, (92, 101, 116), (0, line_y), (width, line_y), 1)
        vanishing_x = width // 2 + int(math.sin(self.store_angle) * 22)
        for top_x in range(-120, width + 121, 80):
            pygame.draw.line(view, (88, 97, 111), (top_x, 0), (vanishing_x, horizon), 1)
        for light_x in (90, 240, 390):
            pygame.draw.polygon(
                view,
                (238, 244, 226),
                ((light_x - 30, 24), (light_x + 30, 24), (light_x + 17, 47), (light_x - 17, 47)),
            )
        walls, cases, _map_width, _map_height = self._store_layout()
        fov = math.radians(70)
        zbuffer: list[float] = [999.0] * width
        for column in range(width):
            ray_angle = self.store_angle - fov / 2 + fov * column / max(1, width - 1)
            ray_x, ray_y = math.cos(ray_angle), math.sin(ray_angle)
            map_x, map_y = int(self.store_player[0]), int(self.store_player[1])
            delta_x = abs(1.0 / ray_x) if abs(ray_x) > 0.0001 else 1e9
            delta_y = abs(1.0 / ray_y) if abs(ray_y) > 0.0001 else 1e9
            step_x = 1 if ray_x >= 0 else -1
            step_y = 1 if ray_y >= 0 else -1
            side_x = ((map_x + 1 - self.store_player[0]) if step_x > 0 else (self.store_player[0] - map_x)) * delta_x
            side_y = ((map_y + 1 - self.store_player[1]) if step_y > 0 else (self.store_player[1] - map_y)) * delta_y
            side = 0
            for _ in range(100):
                if side_x < side_y:
                    side_x += delta_x
                    map_x += step_x
                    side = 0
                else:
                    side_y += delta_y
                    map_y += step_y
                    side = 1
                if (map_x, map_y) in walls:
                    break
            distance = (side_x - delta_x) if side == 0 else (side_y - delta_y)
            distance *= max(0.2, math.cos(ray_angle - self.store_angle))
            zbuffer[column] = max(0.05, distance)
            wall_height = min(height * 3, int(height / max(0.05, distance)))
            top = max(0, horizon - wall_height // 2)
            bottom = min(height - 1, horizon + wall_height // 2)
            kind = self._store_wall_kind(map_x, map_y, _map_width, _map_height)
            if kind == "shelf":
                base = (31, 67, 119) if side == 0 else (22, 48, 91)
                accent = (250, 207, 45)
            elif kind == "entrance":
                base = (74, 137, 163) if side == 0 else (48, 102, 134)
                accent = (184, 239, 255)
            else:
                base = (42, 48, 68) if side == 0 else (30, 35, 52)
                accent = (250, 205, 44)
            pygame.draw.line(view, base, (column, top), (column, bottom))
            if kind == "shelf" and wall_height > 12:
                for ratio in (0.20, 0.40, 0.60, 0.80, 0.97):
                    band_y = top + int((bottom - top) * ratio)
                    view.set_at((column, max(0, min(height - 1, band_y))), accent)
                if column % max(3, min(18, wall_height // 5)) == 0:
                    pygame.draw.line(view, (22, 42, 82), (column, top), (column, bottom), 1)
            elif kind == "entrance" and wall_height > 18:
                if column % max(5, wall_height // 4) == 0:
                    pygame.draw.line(view, accent, (column, top), (column, bottom), 1)
                view.set_at((column, (top + bottom) // 2), (225, 245, 255))
            elif wall_height > 20 and column % 14 == 0:
                pygame.draw.line(view, accent, (column, top), (column, bottom), 1)

        signs = ((10.0, 4.55, "NEW RELEASES"), (6.0, 8.55, "GAMES"), (14.0, 8.55, "MOVIES"))
        for sign_x, sign_y, label in signs:
            projected = self._store_project(sign_x, sign_y, self.store_player, self.store_angle, width, height, fov)
            if projected is None:
                continue
            screen_x, _screen_y, sign_depth = projected
            sign_width = max(34, min(150, int(190 / sign_depth)))
            sign_height = max(10, min(30, sign_width // 5))
            sign_rect = pygame.Rect(screen_x - sign_width // 2, horizon - int(78 / sign_depth), sign_width, sign_height)
            pygame.draw.rect(view, (20, 66, 151), sign_rect, border_radius=2)
            pygame.draw.rect(view, (255, 214, 49), sign_rect, max(1, sign_height // 9), border_radius=2)
            if sign_width >= 70:
                font = pygame.font.SysFont("DejaVu Sans", max(7, sign_height - 5), bold=True)
                text = font.render(label, True, (255, 245, 176))
                view.blit(text, text.get_rect(center=sign_rect.center))

        self.store_focus_index = self._store_focus(cases)
        entries = self._store_entries()
        sprites: list[tuple[float, float, int, int]] = []
        for world_x, world_y, index in cases:
            dx, dy = world_x - self.store_player[0], world_y - self.store_player[1]
            distance = math.hypot(dx, dy)
            angle = self._angle_delta(math.atan2(dy, dx) - self.store_angle)
            depth = distance * math.cos(angle)
            if depth <= 0.08 or abs(angle) > fov * 0.68:
                continue
            screen_x = int((0.5 + angle / fov) * width)
            sprites.append((depth, screen_x, index, int(height * 0.85 / max(0.2, depth))))
        for depth, screen_x, index, sprite_height in sorted(sprites, reverse=True):
            if index >= len(entries):
                continue
            sprite_height = min(height * 2, max(8, sprite_height))
            sprite_width = max(6, int(sprite_height * 0.72))
            left = screen_x - sprite_width // 2
            top = horizon - sprite_height // 2
            cover = self._cover_surface(entries[index])
            case = pygame.Surface((max(1, sprite_width), max(1, sprite_height)), pygame.SRCALPHA)
            border = PINK if index == self.store_focus_index else (236, 218, 105)
            pygame.draw.rect(case, (8, 10, 20), case.get_rect(), border_radius=max(1, sprite_width // 18))
            if cover is not None:
                fitted = pygame.transform.smoothscale(cover, self._fit_size(cover.get_size(), (sprite_width - 4, sprite_height - 4)))
                case.blit(fitted, fitted.get_rect(center=case.get_rect().center))
            else:
                fallback = (52 + (index * 23) % 95, 37 + (index * 31) % 80, 86 + (index * 17) % 110)
                pygame.draw.rect(case, fallback, (2, 2, sprite_width - 4, sprite_height - 4))
                if sprite_width >= 14:
                    initial = str(entries[index].get("title", "?")).strip()[:1].upper() or "?"
                    font = pygame.font.SysFont("DejaVu Sans", max(7, sprite_width // 2), bold=True)
                    glyph = font.render(initial, True, WHITE)
                    case.blit(glyph, glyph.get_rect(center=case.get_rect().center))
            pygame.draw.rect(case, border, case.get_rect(), max(1, sprite_width // 20), border_radius=max(1, sprite_width // 18))
            run_start: int | None = None
            for target_x in range(max(0, left), min(width, left + sprite_width)):
                visible = depth < zbuffer[target_x]
                if visible and run_start is None:
                    run_start = target_x
                if run_start is not None and (not visible or target_x == min(width, left + sprite_width) - 1):
                    run_end = target_x + 1 if visible else target_x
                    source_x = run_start - left
                    view.blit(case, (run_start, top), (source_x, 0, run_end - run_start, sprite_height))
                    run_start = None

        scaled = pygame.transform.scale(view, LOGICAL_SIZE)
        self.canvas.blit(scaled, (0, 0))
        overlay = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        pygame.draw.rect(overlay, (2, 4, 12, 205), (0, 0, 1280, 72))
        pygame.draw.rect(overlay, (2, 4, 12, 205), (0, 650, 1280, 70))
        self.canvas.blit(overlay, (0, 0))
        self._text("PULSEARC • 3D PLAZA", "title", (255, 221, 64), (38, 19))
        focused = "WALK UP TO A CASE" if self.store_focus_index is None else str(entries[self.store_focus_index].get("title", "Unknown"))
        self._text(focused.upper(), "body", WHITE, (38, 662))
        self._text("LEFT MOVE  •  RIGHT LOOK  •  DPAD BROWSE SHELF  •  A INSPECT  •  B EXIT", "small", CYAN, (570, 672))

    def _entry_synopsis(self, entry: dict[str, Any]) -> str:
        content_id = str(entry.get("content_id", ""))
        title = str(entry.get("title", "This title"))
        if title.casefold() == "hell on rails":
            return ""
        synopsis = str(entry.get("synopsis") or self.synopses.get(content_id, "")).strip()
        if synopsis:
            return synopsis
        platform = str(entry.get("platform", "unknown")).replace("-", " ").upper()
        kind = "movie" if is_movie_entry(entry) else "game"
        return f"{title} is an installed {platform} {kind}. A full synopsis has not been downloaded yet."

    def _draw_rotating_case(self, entry: dict[str, Any], center: tuple[int, int]) -> None:
        """Draw a horizontally rotating 3D case with front, spine, and back."""
        cover = self._cover_surface(entry)
        angle = self.store_case_angle
        frontness = math.cos(angle)
        side_sign = 1 if math.sin(angle) >= 0 else -1
        face_width = max(24, int(300 * abs(frontness)))
        side_width = max(5, int(42 * abs(math.sin(angle))))
        height = 430
        face_rect = pygame.Rect(center[0] - face_width // 2, center[1] - height // 2, face_width, height)
        side_x = face_rect.right if side_sign > 0 else face_rect.left
        side = [
            (side_x, face_rect.top),
            (side_x + side_sign * side_width, face_rect.top + 17),
            (side_x + side_sign * side_width, face_rect.bottom - 17),
            (side_x, face_rect.bottom),
        ]
        pygame.draw.polygon(self.canvas, (21, 54, 112), side)
        pygame.draw.polygon(self.canvas, (255, 210, 47), side, 3)
        pygame.draw.rect(self.canvas, (8, 12, 27), face_rect, border_radius=8)
        if frontness >= 0 and cover is not None and face_width > 28:
            fitted = pygame.transform.smoothscale(cover, (max(1, face_width - 12), height - 12))
            self.canvas.blit(fitted, (face_rect.left + 6, face_rect.top + 6))
        elif face_width > 55:
            pygame.draw.rect(self.canvas, (19, 31, 70), face_rect.inflate(-12, -12), border_radius=5)
            label = "BACK COVER" if frontness < 0 else str(entry.get("title", "Unknown")).upper()
            text = self.fonts["body"].render(label, True, (255, 221, 64))
            self.canvas.blit(text, text.get_rect(center=(face_rect.centerx, face_rect.top + 45)))
        pygame.draw.rect(self.canvas, PINK if frontness >= 0 else CYAN, face_rect, 4, border_radius=8)

    def _draw_3d_details(self) -> None:
        self._draw_background()
        entries = self._store_entries()
        if self.store_detail_index is None or self.store_detail_index >= len(entries):
            self._text("THE SELECTED CASE IS NO LONGER AVAILABLE", "body", WHITE, (100, 180))
            return
        entry = entries[self.store_detail_index]
        self._draw_rotating_case(entry, (300, 350))
        title = str(entry.get("title", "Unknown"))
        platform = str(entry.get("platform", "unknown")).upper()
        self._text(title.upper(), "title", PINK, (500, 105))
        self._text(f"SYSTEM  •  {platform}", "body", CYAN, (505, 180))
        kind = "MOVIE" if is_movie_entry(entry) else "GAME"
        self._text(f"MEDIA   •  {kind}", "body", WHITE, (505, 218))
        synopsis = self._entry_synopsis(entry)
        self._text("SYNOPSIS", "body", (255, 221, 64), (505, 274))
        self._wrap(synopsis[:520], (505, 310), 670, WHITE)
        pygame.draw.rect(self.canvas, CYAN, (500, 535, 300, 62), 3)
        self._text("A  PLAY", "menu", WHITE, (530, 552))
        self._text("LEFT / RIGHT OR RIGHT STICK  •  ROTATE CASE", "small", PINK, (505, 625))
        self._text("B  RETURN TO STORE", "body", MUTED, (915, 552))

    def _draw(self) -> None:
        elapsed = time.monotonic() - self.boot_started
        if elapsed < self.boot_duration:
            self._draw_boot(elapsed)
        else:
            self.boot_finished = True
            if self.screensaver_active:
                self._draw_screensaver()
                return
            if self.screen_name == "3d-library":
                self._draw_3d_store()
                return
            if self.screen_name == "3d-details":
                self._draw_3d_details()
                return
            self._draw_background()
            if self.screen_name == "profile-select":
                self._draw_profile_selector()
            elif self.screen_name == "home":
                self._draw_home()
            else:
                self._draw_overlay()

    def _draw_boot(self, elapsed: float) -> None:
        self._draw_background()
        phase = min(1.0, elapsed / 1.65)
        cart_x = int(-230 + phase * 770)
        portal_x, portal_y = 640, 325

        # Pulsing portal and sparks are drawn natively, so no video decoder or
        # desktop compositor is required during startup.
        pulse = 0.5 + 0.5 * math.sin(elapsed * 8.0)
        for radius, color in ((112, PURPLE), (86, PINK), (59, CYAN)):
            width = 2 + int(pulse * 2)
            pygame.draw.circle(self.canvas, color, (portal_x, portal_y), radius, width)
        for index in range(18):
            angle = elapsed * 2.7 + index * (math.tau / 18)
            distance = 128 + 18 * math.sin(elapsed * 5 + index)
            px = int(portal_x + math.cos(angle) * distance)
            py = int(portal_y + math.sin(angle) * distance)
            pygame.draw.circle(self.canvas, CYAN if index % 2 else PINK, (px, py), 2)

        # Generic cartridge sliding into the portal.
        cart = pygame.Rect(cart_x, 270, 190, 112)
        pygame.draw.rect(self.canvas, (13, 17, 41), cart, border_radius=10)
        pygame.draw.rect(self.canvas, CYAN, cart, 3, border_radius=10)
        pygame.draw.rect(self.canvas, (30, 38, 72), (cart_x + 24, 292, 142, 52), border_radius=5)
        pygame.draw.line(self.canvas, PINK, (cart_x + 40, 356), (cart_x + 150, 356), 5)
        if cart.right >= portal_x - 20:
            flash = max(0, int(210 * (1.0 - min(1.0, abs(elapsed - 1.7) / 0.55))))
            if flash:
                overlay = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
                overlay.fill((80, 232, 255, flash // 3))
                self.canvas.blit(overlay, (0, 0))

        reveal = max(0.0, min(1.0, (elapsed - 1.65) / 0.9))
        logo = self.fonts["logo"].render("PULSEARC", True, CYAN)
        logo.set_alpha(int(255 * reveal))
        self.canvas.blit(logo, logo.get_rect(center=(640, 495)))
        sub = self.fonts["small"].render("MEDIA  •  MEMORY  •  MOMENTUM", True, PINK)
        sub.set_alpha(int(255 * reveal))
        self.canvas.blit(sub, sub.get_rect(center=(640, 548)))
        progress = max(0.0, min(1.0, elapsed / BOOT_SECONDS))
        pygame.draw.rect(self.canvas, (34, 41, 75), (430, 595, 420, 6), border_radius=3)
        pygame.draw.rect(self.canvas, PINK, (430, 595, int(420 * progress), 6), border_radius=3)

    def _draw_background(self) -> None:
        if self.theme_video is not None:
            frame = self.theme_video.surface()
            if frame is not None:
                self.canvas.blit(pygame.transform.scale(frame, LOGICAL_SIZE), (0, 0))
                shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
                shade.fill((2, 3, 15, 58))
                self.canvas.blit(shade, (0, 0))
                return
        style = self.theme.background_style if self.theme is not None else ""
        if style:
            self._draw_native_theme_background(style)
            return
        if self.theme_background is not None:
            self.canvas.blit(self.theme_background, (0, 0))
            shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
            shade.fill((2, 3, 15, 82))
            self.canvas.blit(shade, (0, 0))
            return
        self.canvas.fill((2, 3, 15))
        now = time.monotonic()
        for i in range(42):
            x = (i * 977) % 1280
            y = (i * 431) % 430
            glow = 90 + int(80 * math.sin(now * 0.7 + i))
            self.canvas.fill((70, 150, min(255, glow + 90)), (x, y, 2, 2))
        horizon = 485
        pygame.draw.line(self.canvas, PINK, (0, horizon), (1280, horizon), 2)
        for i in range(1, 18):
            t = i / 18
            y = int(horizon + (t**2.2) * (720 - horizon))
            pygame.draw.line(self.canvas, (32, 100, 150), (0, y), (1280, y), 1)
        for i in range(-14, 15):
            x = int(640 + i * 106)
            pygame.draw.line(self.canvas, (105, 30, 108), (640, horizon), (x, 720), 1)

    def _draw_native_theme_background(self, style: str) -> None:
        """Resolution-independent animated backgrounds ported from PlayFusion."""
        now = time.monotonic()
        if style in {"retro-laser-grid", "pulsearc-classic"}:
            self.canvas.fill((2, 3, 15))
            horizon = 465
            sun_y = 315 + int(math.sin(now * 0.35) * 8)
            pygame.draw.circle(self.canvas, PINK, (640, sun_y), 112)
            for stripe in range(9):
                pygame.draw.rect(self.canvas, (2, 3, 15), (525, sun_y - 73 + stripe * 18, 230, 8))
            for index in range(1, 22):
                t = index / 22
                y = int(horizon + (t ** 2.0) * (720 - horizon))
                pygame.draw.line(self.canvas, CYAN if index % 2 else PURPLE, (0, y), (1280, y), 1)
            drift = int((now * 32) % 90)
            for index in range(-17, 18):
                pygame.draw.line(self.canvas, PINK, (640, horizon), (640 + index * 92 + drift, 720), 1)
            return
        if style == "digital-circuit-rain":
            self.canvas.fill((1, 7, 14))
            for column in range(42):
                x = 12 + column * 31
                head = int((now * (52 + column % 6 * 9) + column * 83) % 850) - 90
                color = CYAN if column % 3 else PINK
                for trail in range(7):
                    y = head - trail * 22
                    if 0 <= y < 720:
                        fade = max(35, 230 - trail * 29)
                        pygame.draw.line(self.canvas, (*color, fade), (x, y), (x + (column % 2) * 12, y + 13), 2)
                        if trail % 2 == 0:
                            pygame.draw.circle(self.canvas, color, (x, y), 2)
            return
        if style == "vibrant-spectrum":
            self.canvas.fill((16, 4, 31))
            palette = (CYAN, PINK, PURPLE, (255, 136, 48), (80, 255, 160))
            for band in range(15):
                points = []
                for x in range(-20, 1301, 24):
                    y = 90 + band * 43 + math.sin(x * 0.009 + now * 1.4 + band * 0.55) * 30
                    points.append((x, int(y)))
                pygame.draw.lines(self.canvas, palette[band % len(palette)], False, points, 3)
            return
        if style == "sunset-pop":
            self.canvas.fill((27, 3, 44))
            for y in range(720):
                ratio = y / 720
                pygame.draw.line(self.canvas, (int(24 + ratio * 30), 3, int(50 + ratio * 48)), (0, y), (1280, y))
            sun = (640, 250)
            pygame.draw.circle(self.canvas, (255, 88, 170), sun, 125)
            for stripe in range(10):
                pygame.draw.rect(self.canvas, (44, 5, 61), (510, 170 + stripe * 19, 260, 8))
            horizon = 455
            city = [(x, horizon - 25 - ((x * 37) % 135)) for x in range(0, 1281, 42)]
            for x, top in city:
                pygame.draw.rect(self.canvas, (7, 8, 30), (x, top, 35, horizon - top))
            for row in range(1, 18):
                t = row / 18
                y = int(horizon + t * t * (720 - horizon))
                pygame.draw.line(self.canvas, (90, 28, 144), (0, y), (1280, y), 1)
            offset = int((now * 25) % 70)
            for col in range(-18, 19):
                pygame.draw.line(self.canvas, (20, 130, 210), (640, horizon), (640 + col * 82 + offset, 720), 1)
            return
        if style == "aqua-pulse":
            self.canvas.fill((0, 14, 28))
            center = (640, 370)
            for ring in range(15):
                radius = int(((now * 90 + ring * 62) % 930))
                color = CYAN if ring % 2 else (40, 170, 230)
                pygame.draw.ellipse(self.canvas, color, (center[0] - radius, center[1] - radius // 2, radius * 2, radius), 2)
            for ray in range(18):
                angle = now * 0.18 + ray * math.tau / 18
                end = (center[0] + int(math.cos(angle) * 780), center[1] + int(math.sin(angle) * 420))
                pygame.draw.line(self.canvas, (15, 75, 120), center, end, 1)
            return
        if style == "xbox-2-0":
            self.canvas.fill((0, 12, 2))
            center = (640 + int(math.sin(now * 0.35) * 70), 360 + int(math.cos(now * 0.29) * 30))
            for radius in range(460, 35, -32):
                pulse = 0.5 + 0.5 * math.sin(now * 1.8 + radius * 0.025)
                green = int(28 + pulse * 105)
                pygame.draw.circle(self.canvas, (6, green, 18), center, radius, 3)
            for index in range(60):
                angle = index * 2.399963 + now * 0.15
                distance = 60 + ((index * 47 + int(now * 35)) % 610)
                pos = (center[0] + int(math.cos(angle) * distance), center[1] + int(math.sin(angle) * distance * 0.55))
                pygame.draw.circle(self.canvas, (120, 245, 30), pos, 1 + index % 3)
            return
        self.canvas.fill((2, 3, 15))

    def _draw_screensaver(self) -> None:
        now = time.monotonic()
        saver = str(self.settings.get("screensaver", "retro-grid"))
        self.canvas.fill((1, 2, 12))
        if saver == "starfield":
            for index in range(150):
                depth = ((now * 0.18 + index * 0.031) % 1.0) ** 2
                angle = index * 2.399963
                radius = depth * 720
                x = int(640 + math.cos(angle) * radius)
                y = int(360 + math.sin(angle) * radius * 0.56)
                size = 1 + int(depth * 4)
                color = CYAN if index % 3 else PINK
                pygame.draw.circle(self.canvas, color, (x, y), size)
        elif saver == "bouncing-orb":
            x = 90 + int((math.sin(now * 0.71) + 1) * 550)
            y = 90 + int((math.sin(now * 0.93 + 1.2) + 1) * 270)
            for radius, color in ((74, PURPLE), (54, PINK), (34, CYAN)):
                pygame.draw.circle(self.canvas, color, (x, y), radius, 4)
            self._text("PULSEARC", "logo", WHITE, (x - 125, y + 90))
        else:
            horizon = 345
            for index in range(1, 24):
                t = index / 24
                y = int(horizon + (t**2.0) * (720 - horizon))
                pygame.draw.line(self.canvas, CYAN if index % 2 else PURPLE, (0, y), (1280, y), 1)
            shift = int((now * 70) % 100)
            for index in range(-16, 17):
                x = 640 + index * 95 + shift
                pygame.draw.line(self.canvas, PINK, (640, horizon), (x, 720), 1)
            sun_y = 225 + int(math.sin(now * 0.45) * 22)
            pygame.draw.circle(self.canvas, PINK, (640, sun_y), 96)
            for stripe in range(8):
                pygame.draw.rect(self.canvas, (1, 2, 12), (540, sun_y - 65 + stripe * 18, 200, 7))
            logo = self.fonts["logo"].render("PULSEARC", True, WHITE)
            self.canvas.blit(logo, logo.get_rect(center=(640, 520)))

    def _text(self, text: str, font: str, color: tuple[int, int, int], pos: tuple[int, int]) -> None:
        self.canvas.blit(self.fonts[font].render(text, True, color), pos)

    def _translucent_panel(self, rect: pygame.Rect, alpha: int | None = None, radius: int = 10) -> None:
        """Draw a theme-tinted glass panel without hiding the background."""
        opacity = alpha
        if opacity is None:
            opacity = self.theme.panel_opacity if self.theme is not None else 68
        glass = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(glass, (*PANEL[:3], max(0, min(255, opacity))), glass.get_rect(), border_radius=radius)
        self.canvas.blit(glass, rect.topleft)

    def _draw_profile_avatar(self, profile: dict[str, str], rect: pygame.Rect) -> None:
        pygame.draw.rect(self.canvas, PANEL[:3], rect, border_radius=14)
        avatar = self._profile_avatar(profile)
        if avatar is None:
            pygame.draw.circle(self.canvas, CYAN, rect.center, min(rect.width, rect.height) // 3, 4)
            initial = self.fonts["logo"].render(profile["name"][:1].upper(), True, WHITE)
            self.canvas.blit(initial, initial.get_rect(center=rect.center))
            return
        fitted = pygame.transform.smoothscale(avatar, self._fit_size(avatar.get_size(), rect.size))
        self.canvas.blit(fitted, fitted.get_rect(center=rect.center))

    def _draw_profile_selector(self) -> None:
        shade = pygame.Surface(LOGICAL_SIZE, pygame.SRCALPHA)
        shade.fill((*PANEL[:3], 120))
        self.canvas.blit(shade, (0, 0))
        logo = self.fonts["logo"].render("PULSEARC", True, CYAN)
        self.canvas.blit(logo, logo.get_rect(center=(640, 82)))
        title = self.fonts["title"].render("WHO IS PLAYING?", True, WHITE)
        self.canvas.blit(title, title.get_rect(center=(640, 145)))
        count = max(1, len(self.profiles))
        card_width, gap = 240, 28
        start_x = (1280 - (count * card_width + (count - 1) * gap)) // 2
        for index, profile in enumerate(self.profiles):
            x = start_x + index * (card_width + gap)
            chosen = index == self.overlay_selection
            card = pygame.Rect(x, 205, card_width, 340)
            pygame.draw.rect(self.canvas, PANEL[:3], card, border_radius=18)
            pygame.draw.rect(self.canvas, PINK if chosen else CYAN, card, 5 if chosen else 2, border_radius=18)
            self._draw_profile_avatar(profile, pygame.Rect(x + 25, 232, 190, 190))
            name = self.fonts["menu"].render(profile["name"], True, WHITE if chosen else MUTED)
            self.canvas.blit(name, name.get_rect(center=(x + card_width // 2, 465)))
            if profile["id"] == self.profile_id:
                active = self.fonts["small"].render("LAST USED", True, GREEN)
                self.canvas.blit(active, active.get_rect(center=(x + card_width // 2, 510)))
        hint = self.fonts["body"].render("A  SELECT PROFILE", True, GREEN)
        self.canvas.blit(hint, hint.get_rect(center=(640, 615)))

    def _draw_home(self) -> None:
        profile = next((item for item in self.profiles if item["id"] == self.profile_id), self.profiles[0])
        profile_left = self.theme is not None and self.theme.profile_position == "left"
        logo_x = 300 if profile_left else 54
        self._text("PULSEARC", "logo", CYAN, (logo_x, 35))
        self._text("DIRECT MEDIA GAMING SYSTEM  •  NATIVE SHELL", "small", PURPLE, (logo_x + 4, 98))
        badge_x = 54 if profile_left else 1160
        self._draw_profile_avatar(profile, pygame.Rect(badge_x, 34, 54, 54))
        profile_label = self.fonts["small"].render(self.profile_name.upper(), True, PINK)
        if profile_left:
            self.canvas.blit(profile_label, (badge_x + 64, 53))
        else:
            self.canvas.blit(profile_label, profile_label.get_rect(right=badge_x - 12, centery=61))
        menu_right = self.theme is not None and self.theme.menu_position == "right"
        menu_x = 775 if menu_right else 62
        text_x = menu_x + 8
        panel_x = 54 if menu_right else 570
        for index, (title, _description) in enumerate(MENU):
            y = 116 + index * 46
            disabled = title == "PLAY" and not any(is_external_entry(entry) for entry in self.library)
            if index == self.selection:
                pygame.draw.rect(self.canvas, CYAN if not disabled else DISABLED, (menu_x, y - 2, 435, 43), 2)
            color = DISABLED if disabled else (WHITE if index == self.selection else MUTED)
            self._text(title, "menu", color, (text_x, y + 6))
        home_panel = pygame.Rect(panel_x, 165, 640, 370)
        self._translucent_panel(home_panel)
        pygame.draw.rect(self.canvas, CYAN, home_panel, 2, border_radius=10)
        self._text("READY", "title", PINK, (panel_x + 18, 178))
        self._wrap(MENU[self.selection][1], (panel_x + 18, 246), 600, WHITE)
        home_status = "READING OPTICAL DISC…" if self.optical_media_reading else self.status
        self._text(home_status, "small", MUTED, (panel_x + 18, 575))
        if MENU[self.selection][0] == "PLAY" and any(is_external_entry(entry) for entry in self.library):
            self._text("A  PLAY    X  INSTALL", "small", GREEN, (panel_x + 18, 605))
        footer = (
            f"DEVELOPMENT SSH  |  gamer@{self.address}  |  password {ssh_password()}"
            f"  |  {internal_free_space()}"
        )
        self._text(footer, "small", GREEN, (54, 680))

    def _draw_overlay(self) -> None:
        pygame.draw.rect(self.canvas, PANEL[:3], (65, 70, 1150, 590))
        pygame.draw.rect(self.canvas, CYAN, (65, 70, 1150, 590), 2)
        if self.screen_name == "library-games":
            heading = "LIBRARY"
        elif self.screen_name == "install-progress":
            heading = "INSTALL GAME"
        else:
            heading = self.screen_name.upper()
        self._text(heading, "title", PINK, (95, 92))
        if self.screen_name == "play":
            self._draw_library(self._entries_for_screen())
        elif self.screen_name == "install-progress":
            self._draw_install_progress()
        elif self.screen_name == "library":
            self._draw_library_systems()
        elif self.screen_name == "library-games":
            self._draw_library_games()
        elif self.screen_name == "power":
            self._draw_power()
        elif self.screen_name == "controllers":
            lines = (
                "XBOX-STYLE UNIVERSAL DEFAULT",
                "A/South: Select   •   B/East: Back",
                "D-pad or left stick: Navigate",
                "View + Menu: Exit game",
                f"Connected controllers: {len(self.controllers)}",
            )
            self._draw_lines(lines)
        elif self.screen_name == "settings":
            self._draw_settings()
        elif self.screen_name == "runtime-settings":
            self._draw_runtime_settings()
        elif self.screen_name == "music":
            self._draw_music()
        elif self.screen_name == "radio":
            self._draw_radio()
        elif self.screen_name == "tv":
            self._draw_simple_menu(self.tv_actions, "FULL FREE TV CATALOG AND PRIVATE M3U / XTREAM PROVIDERS")
        elif self.screen_name == "apps":
            self._draw_simple_menu(self.apps_actions, "CONTROLLER-FRIENDLY APPS; WEB SERVICES MAY REQUIRE AN ACCOUNT")
        elif self.screen_name == "downloads":
            self._draw_download_archives()
        elif self.screen_name == "tv-groups":
            self._draw_tv_groups()
        elif self.screen_name == "tv-channels":
            self._draw_tv_channels()
        elif self.screen_name == "tv-sources":
            self._draw_tv_sources()
        elif self.screen_name == "dvr":
            self._draw_dvr()
        elif self.screen_name == "wifi":
            self._draw_wifi()
        elif self.screen_name == "wifi-password":
            self._draw_wifi_password()
        elif self.screen_name == "bluetooth":
            self._draw_bluetooth()
        elif self.screen_name == "saves":
            self._draw_saves()
        elif self.screen_name == "cheats":
            self._draw_cheat_systems()
        elif self.screen_name == "cheat-games":
            self._draw_cheat_games()
        elif self.screen_name == "cheat-details":
            self._draw_cheat_details()
        elif self.screen_name == "extras":
            recorder = "STOP & SAVE SCREEN RECORDING" if self.screen_record_process is not None and self.screen_record_process.poll() is None else "START SCREEN RECORDING"
            items = tuple(recorder if item == "SCREEN RECORDING" else item for item in self.extras_items)
            self._draw_simple_menu(items, "PROFILES, THEMES, INPUT, NETWORK, BIOS, RECORDING, AND SAFE UPDATES")
        elif self.screen_name == "profiles":
            self._draw_profiles()
        elif self.screen_name == "profile-delete-confirm":
            self._draw_profile_delete_confirm()
        elif self.screen_name == "profile-rename":
            self._draw_profile_rename()
        elif self.screen_name == "themes":
            self._draw_themes()
        elif self.screen_name == "screensavers":
            self._draw_screensavers()
        elif self.screen_name == "controller-remapping":
            self._draw_simple_menu(
                ("VIEW CONNECTED CONTROLLERS / XBOX DEFAULTS", "BACK"),
                "Xbox-style defaults are shared; per-game mappings remain isolated by profile",
            )
        elif self.screen_name == "antimicrox":
            self._draw_simple_menu(
                ("IMPORT .AMGP / .XML PROFILES FROM USB OR SD", "BACK"),
                "USB path: PulseArc/Controllers  •  intended only for keyboard/mouse PC games",
            )
        elif self.screen_name == "bios":
            self._draw_bios_manager()
        else:
            data = self._manager_data(self.screen_name)
            lines = tuple(data) if data else (f"No {self.screen_name} entries exist for this profile yet.",)
            self._draw_lines(lines)
        if self.screen_name not in ("settings", "play"):
            self._text("B  BACK", "body", MUTED, (95, 610))

    def _draw_install_progress(self) -> None:
        """Render optical/removable copy progress without blocking the UI."""
        elapsed = max(0.001, time.monotonic() - self.install_started)
        copied_mb = self.install_bytes / 1048576
        total_mb = self.install_total / 1048576
        speed = copied_mb / elapsed
        progress = max(0.0, min(1.0, self.install_progress))

        self._text(self.install_title.upper(), "menu", WHITE, (95, 165))
        self._text(self.install_phase, "body", GREEN if self.install_result != "failed" else PINK, (95, 225))
        bar = pygame.Rect(95, 285, 1050, 42)
        pygame.draw.rect(self.canvas, (23, 28, 60), bar, border_radius=8)
        if progress > 0:
            fill = pygame.Rect(bar.x, bar.y, max(8, round(bar.width * progress)), bar.height)
            pygame.draw.rect(self.canvas, CYAN if not self.install_result else GREEN, fill, border_radius=8)
        pygame.draw.rect(self.canvas, WHITE, bar, 2, border_radius=8)
        self._text(f"{progress * 100:5.1f}%", "title", WHITE, (95, 350))
        if self.install_total > 0:
            amount = f"{copied_mb:,.1f} MB OF {total_mb:,.1f} MB"
        else:
            amount = f"{copied_mb:,.1f} MB COPIED"
        self._text(amount, "body", MUTED, (95, 420))
        if not self.install_result:
            self._text(f"{speed:,.1f} MB/S  •  KEEP THE DISC INSERTED", "body", MUTED, (95, 465))
            self._text("INSTALLATION IS VERIFIED BEFORE IT APPEARS IN THE LIBRARY", "small", PURPLE, (95, 520))
        else:
            result_text = self.status if self.install_result == "failed" else self.install_phase
            self._wrap(result_text, (95, 465), 1020, WHITE)
            self._text("A OR B  RETURN", "body", GREEN, (95, 550))

    def _draw_library(self, entries: list[dict[str, Any]]) -> None:
        if not entries:
            empty = "No installed local games." if self.screen_name == "library" else "No external games or media detected."
            self._text(empty, "body", WHITE, (95, 165))
        visible_rows = 8
        selected_entry = min(self.overlay_selection, max(0, len(entries) - 1))
        start = max(0, min(selected_entry - visible_rows + 1, len(entries) - visible_rows))
        for row, entry in enumerate(entries[start : start + visible_rows]):
            index = start + row
            y = 155 + row * 52
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 780, 44), 2)
            title = str(entry.get("title", "Unknown"))
            platform = str(entry.get("platform") or entry.get("system") or "unknown").upper()
            self._text(f"{title}    [{platform}]", "body", WHITE, (105, y + 10))
        if entries and self.overlay_selection < len(entries):
            self._draw_cover(entries[self.overlay_selection], (920, 155, 210, 294))
        install_all_index = len(entries)
        y = 155 + min(len(entries), visible_rows) * 52
        if self.overlay_selection == install_all_index:
            pygame.draw.rect(self.canvas, PINK, (90, y, 780, 44), 2)
        install_label = (
            "INSTALL DISC"
            if len(entries) == 1 and str(entries[0].get("path", "")).startswith("/dev/")
            else "INSTALL ALL GAMES"
        )
        self._text(install_label, "body", GREEN, (105, y + 10))
        close_index = len(entries) + 1
        y += 52
        if self.overlay_selection == close_index:
            pygame.draw.rect(self.canvas, CYAN, (90, y, 780, 44), 2)
        self._text("BACK", "body", MUTED, (105, y + 10))
        self._text("A  PLAY / CHOOSE     X  INSTALL SELECTED", "small", MUTED, (90, 682))

    def _draw_library_systems(self) -> None:
        systems = self._library_systems()
        self._text("CHOOSE A SYSTEM FOLDER", "body", MUTED, (95, 140))
        page_size = 8
        selected = min(self.overlay_selection, max(0, len(systems) - 1))
        start = (selected // page_size) * page_size if systems else 0
        for offset, (platform, games) in enumerate(systems[start:start + page_size]):
            index = start + offset
            column, row = offset % 4, offset // 4
            x, y = 92 + column * 275, 180 + row * 190
            chosen = index == self.overlay_selection
            color = PINK if chosen else CYAN
            pygame.draw.rect(self.canvas, (13, 17, 43), (x, y, 245, 155), border_radius=10)
            pygame.draw.rect(self.canvas, color, (x, y, 245, 155), 3 if chosen else 1, border_radius=10)
            pygame.draw.rect(self.canvas, (32, 41, 84), (x + 22, y + 29, 82, 65), border_radius=5)
            pygame.draw.rect(self.canvas, color, (x + 33, y + 18, 42, 18), border_radius=4)
            self._text(self._system_label(platform)[:22], "body", WHITE, (x + 18, y + 108))
            self._text(f"{games} GAME{'S' if games != 1 else ''}", "small", GREEN, (x + 18, y + 135))
        self._draw_gallery_back(len(systems))

    def _draw_library_games(self) -> None:
        entries = self._library_games_for_system()
        self._text(f"{self._system_label(self.library_system)}  /  CHOOSE A GAME", "body", MUTED, (95, 140))
        page_size = 8
        selected = min(self.overlay_selection, max(0, len(entries) - 1))
        start = (selected // page_size) * page_size if entries else 0
        for offset, entry in enumerate(entries[start:start + page_size]):
            index = start + offset
            column, row = offset % 4, offset // 4
            x, y = 92 + column * 275, 170 + row * 205
            chosen = index == self.overlay_selection
            pygame.draw.rect(self.canvas, (13, 17, 43), (x, y, 245, 180), border_radius=10)
            pygame.draw.rect(self.canvas, PINK if chosen else CYAN, (x, y, 245, 180), 3 if chosen else 1, border_radius=10)
            self._draw_cover(entry, (x + 12, y + 12, 82, 116))
            self._wrap(str(entry.get("title", "Unknown"))[:46], (x + 105, y + 17), 125, WHITE)
            self._text("A  PLAY", "small", GREEN, (x + 105, y + 142))
        self._draw_gallery_back(len(entries))

    def _draw_cover(self, entry: dict[str, Any], rect: tuple[int, int, int, int]) -> None:
        surface = self._cover_surface(entry)
        pygame.draw.rect(self.canvas, (15, 19, 44), rect)
        pygame.draw.rect(self.canvas, CYAN, rect, 2)
        if surface is None:
            mark = self.fonts["logo"].render("?", True, MUTED)
            self.canvas.blit(mark, mark.get_rect(center=pygame.Rect(rect).center))
            return
        fitted = pygame.transform.smoothscale(surface, self._fit_size(surface.get_size(), (rect[2] - 8, rect[3] - 8)))
        self.canvas.blit(fitted, fitted.get_rect(center=pygame.Rect(rect).center))

    def _cover_surface(self, entry: dict[str, Any]) -> pygame.Surface | None:
        path = self.covers.get(str(entry.get("content_id", ""))) or str(entry.get("cover_path", ""))
        surface = self.cover_images.get(path)
        if path and path not in self.cover_images:
            try:
                surface = pygame.image.load(path).convert_alpha()
            except (OSError, pygame.error):
                surface = None
            self.cover_images[path] = surface
        return surface

    @staticmethod
    def _fit_size(source: tuple[int, int], bounds: tuple[int, int]) -> tuple[int, int]:
        scale = min(bounds[0] / max(1, source[0]), bounds[1] / max(1, source[1]))
        return max(1, round(source[0] * scale)), max(1, round(source[1] * scale))

    def _draw_power(self) -> None:
        for index, title in enumerate((*self.power_items, "CANCEL")):
            y = 175 + index * 64
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 52), 2)
            self._text(title, "menu", WHITE, (105, y + 12))

    def _draw_profiles(self) -> None:
        self._text("GAMES ARE SHARED; SAVES, SETTINGS, CHEATS, AND CONTROLS ARE SEPARATE", "small", MUTED, (95, 140))
        for index, profile in enumerate(self.profiles):
            x = 95 + index * 260
            chosen = index == self.overlay_selection
            card = pygame.Rect(x, 180, 230, 300)
            pygame.draw.rect(self.canvas, (14, 17, 39), card, border_radius=15)
            pygame.draw.rect(self.canvas, PINK if chosen else CYAN, card, 4 if chosen else 2, border_radius=15)
            self._draw_profile_avatar(profile, pygame.Rect(x + 25, 202, 180, 180))
            active = profile["id"] == self.profile_id
            label = self.fonts["body"].render(profile["name"], True, GREEN if active else WHITE)
            self.canvas.blit(label, label.get_rect(center=(x + 115, 420)))
            if active:
                tag = self.fonts["small"].render("ACTIVE", True, GREEN)
                self.canvas.blit(tag, tag.get_rect(center=(x + 115, 454)))
        action_index = len(self.profiles)
        if len(self.profiles) < MAX_PROFILES:
            chosen = self.overlay_selection == action_index
            pygame.draw.rect(self.canvas, PINK if chosen else CYAN, (95, 515, 500, 52), 3 if chosen else 1, border_radius=8)
            self._text("ADD PROFILE", "menu", WHITE, (115, 527))
            back_index = action_index + 1
        else:
            back_index = action_index
        chosen = self.overlay_selection == back_index
        pygame.draw.rect(self.canvas, PINK if chosen else CYAN, (620, 515, 500, 52), 3 if chosen else 1, border_radius=8)
        self._text("BACK", "menu", WHITE, (640, 527))
        self._text("A ACTIVATE / ADD  •  Y RENAME  •  LB/RB IMAGE  •  X REMOVE", "small", GREEN, (105, 600))

    def _draw_profile_rename(self) -> None:
        self._text("RENAME PROFILE", "body", MUTED, (95, 140))
        pygame.draw.rect(self.canvas, (14, 17, 39), (95, 175, 1050, 58), border_radius=8)
        pygame.draw.rect(self.canvas, CYAN, (95, 175, 1050, 58), 2, border_radius=8)
        self._text(self.profile_rename_text or "TYPE A NAME", "menu", WHITE, (112, 190))
        for index, key in enumerate(PROFILE_KEYS):
            column, row = index % ONSCREEN_COLUMNS, index // ONSCREEN_COLUMNS
            x, y = 95 + column * 105, 270 + row * 64
            width = 96
            chosen = index == self.overlay_selection
            pygame.draw.rect(self.canvas, PINK if chosen else (45, 52, 82), (x, y, width, 48), 3 if chosen else 1, border_radius=6)
            label = key if len(key) <= 3 else {"BACKSPACE": "DELETE", "SAVE": "SAVE", "CANCEL": "CANCEL"}.get(key, key)
            rendered = self.fonts["small"].render(label, True, WHITE)
            self.canvas.blit(rendered, rendered.get_rect(center=(x + width // 2, y + 24)))
        self._text("KEYBOARD TYPING ALSO WORKS  •  A SELECT  •  B CANCEL", "small", GREEN, (105, 605))

    def _draw_profile_delete_confirm(self) -> None:
        profile = next((item for item in self.profiles if item["id"] == self.pending_profile_delete), None)
        name = profile["name"] if profile else "PROFILE"
        self._text(f"REMOVE {name.upper()}?", "title", PINK, (95, 175))
        self._wrap("The profile disappears from the selector. Its saves and settings are archived for recovery rather than erased.", (95, 235), 1000, WHITE)
        for index, label in enumerate(("YES — ARCHIVE AND REMOVE", "NO — KEEP PROFILE")):
            y = 370 + index * 75
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, CYAN, (95, y, 850, 58), 3, border_radius=8)
            self._text(label, "menu", WHITE, (115, y + 15))

    def _draw_themes(self) -> None:
        items = [*(theme.name for theme in self.themes), "IMPORT THEME ZIP FROM USB / SD", "BACK"]
        visible = 7
        start = max(0, min(self.overlay_selection - visible + 1, len(items) - visible))
        for row, title in enumerate(items[start:start + visible]):
            index = start + row
            y = 165 + row * 58
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 720, 48), 2, border_radius=6)
            active = index < len(self.themes) and self.theme is not None and self.themes[index].theme_id == self.theme.theme_id
            self._text(("ACTIVE  •  " if active else "") + str(title), "body", GREEN if active else WHITE, (105, y + 12))
        if self.overlay_selection < len(self.themes):
            theme = self.themes[self.overlay_selection]
            preview = theme.preview or (theme.background if theme.background and theme.background.suffix.casefold() != ".mp4" else None)
            if preview:
                self._draw_cover({"cover_path": str(preview)}, (865, 165, 280, 245))
            else:
                self._draw_theme_preview(theme, pygame.Rect(865, 165, 280, 245))
            self._wrap(theme.description or f"Theme by {theme.author or 'PulseArc'}", (865, 435), 280, MUTED)
        self._text("A APPLY / IMPORT  •  USB: PulseArc/Themes/*.zip", "small", GREEN, (105, 605))

    def _draw_theme_preview(self, theme: Theme, rect: pygame.Rect) -> None:
        accent = self._hex_color(theme.accent, CYAN)
        secondary = self._hex_color(theme.secondary, PINK)
        panel = self._hex_color(theme.panel, PANEL[:3])
        pygame.draw.rect(self.canvas, panel, rect, border_radius=9)
        horizon = rect.y + int(rect.height * 0.58)
        if theme.background_style == "digital-circuit-rain":
            for column in range(12):
                x = rect.x + 10 + column * 23
                pygame.draw.line(self.canvas, accent if column % 2 else secondary, (x, rect.y + 18), (x, rect.bottom - 18), 2)
        elif theme.background_style in {"sunset-pop", "retro-laser-grid", "pulsearc-classic"}:
            pygame.draw.circle(self.canvas, secondary, (rect.centerx, rect.y + 92), 55)
            for row in range(7):
                y = horizon + row * 17
                pygame.draw.line(self.canvas, accent, (rect.x + 8, y), (rect.right - 8, y), 1)
            for column in range(-5, 6):
                pygame.draw.line(self.canvas, secondary, (rect.centerx, horizon), (rect.centerx + column * 31, rect.bottom - 8), 1)
        elif theme.background_style == "aqua-pulse":
            for radius in range(24, 135, 22):
                pygame.draw.ellipse(self.canvas, accent if radius % 2 else secondary, (rect.centerx - radius, rect.centery - radius // 2, radius * 2, radius), 2)
        else:
            for row in range(8):
                y = rect.y + 20 + row * 27
                pygame.draw.line(self.canvas, accent if row % 2 else secondary, (rect.x + 12, y), (rect.right - 12, y), 3)
        pygame.draw.rect(self.canvas, accent, rect, 2, border_radius=9)

    def _draw_screensavers(self) -> None:
        selected_id = str(self.settings.get("screensaver", "retro-grid"))
        items = [*(name for _identifier, name in self.screensaver_choices), "BACK"]
        self._text(f"STARTS AFTER {self.settings.get('screensaver_idle', 30)} SECONDS ON THE HOME SCREEN", "body", MUTED, (95, 140))
        for index, title in enumerate(items):
            y = 190 + index * 68
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 54), 2, border_radius=7)
            active = index < len(self.screensaver_choices) and self.screensaver_choices[index][0] == selected_id
            self._text(("ACTIVE  •  " if active else "") + title, "menu", GREEN if active else WHITE, (110, y + 13))

    def _draw_music(self) -> None:
        music = self._music_entries()
        music_count = len(music)
        self._text(f"Detected music files: {music_count}", "body", MUTED, (95, 145))
        items = [*self.music_actions, *(f"TRACK  •  {item.get('title', 'Unknown')}" for item in music), "BACK"]
        visible_rows = 7
        start = max(0, min(self.overlay_selection - visible_rows + 1, len(items) - visible_rows))
        for row, title in enumerate(items[start : start + visible_rows]):
            index = start + row
            y = 190 + row * 58
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 48), 2)
            self._text(str(title), "body", WHITE, (105, y + 12))

    def _draw_radio(self) -> None:
        self._text("LIVE INTERNET RADIO  •  PROJECTM VISUALS INCLUDED", "body", MUTED, (95, 145))
        items = [
            *(f"{station['genre']}  •  {station['name']}" for station in RADIO_STATIONS),
            "BACK",
        ]
        visible_rows = 7
        start = max(0, min(self.overlay_selection - visible_rows + 1, len(items) - visible_rows))
        for row, title in enumerate(items[start : start + visible_rows]):
            index = start + row
            y = 190 + row * 58
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 48), 2)
            self._text(str(title), "body", WHITE, (105, y + 12))

    def _draw_tv_groups(self) -> None:
        self._text(f"{len(self.tv_channels)} CHANNELS / MOVIES  •  CHOOSE A GROUP", "body", MUTED, (95, 140))
        items = [*(f"{name}  •  {count}" for name, count in self.tv_groups), "BACK"]
        visible_rows = 8
        start = max(0, min(self.overlay_selection - visible_rows + 1, len(items) - visible_rows))
        for row, title in enumerate(items[start:start + visible_rows]):
            index = start + row
            y = 172 + row * 52
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 43), 2)
            self._text(str(title)[:82], "body", WHITE, (105, y + 9))

    def _draw_tv_channels(self) -> None:
        channels = self._tv_channels_for_group()
        recording = f"  •  RECORDING {self.dvr_title.upper()}" if self.dvr_process is not None and self.dvr_process.poll() is None else ""
        self._text(f"{self.tv_group}  •  {len(channels)} ITEMS{recording}", "body", MUTED, (95, 140))
        if self.tv_group.startswith("VOD / "):
            self._draw_tv_vod_gallery(channels)
            return
        items = [*(channel.get("name", "CHANNEL") for channel in channels), "BACK"]
        visible_rows = 8
        start = max(0, min(self.overlay_selection - visible_rows + 1, len(items) - visible_rows))
        for row, title in enumerate(items[start:start + visible_rows]):
            index = start + row
            y = 172 + row * 52
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 700, 43), 2)
            self._text(str(title)[:38], "body", WHITE, (105, y + 9))
        if 0 <= self.overlay_selection < len(channels):
            self._draw_tv_guide(channels[self.overlay_selection])
        self._text("A PLAY  •  RB/R1 START OR STOP DVR RECORDING", "small", GREEN, (105, 605))

    def _draw_tv_guide(self, channel: dict[str, str]) -> None:
        panel = pygame.Rect(820, 170, 370, 390)
        pygame.draw.rect(self.canvas, (10, 13, 31), panel, border_radius=10)
        pygame.draw.rect(self.canvas, CYAN, panel, 2, border_radius=10)
        self._text("TV GUIDE  •  EASTERN TIME", "body", CYAN, (842, 190))
        stream_id = str(channel.get("stream_id", ""))
        programs = self._request_tv_epg(channel)
        if not stream_id or str(channel.get("media_type", "")) != "live":
            self._text("NO GUIDE DATA", "body", MUTED, (842, 240))
            return
        if programs is None:
            self._text("LOADING GUIDE...", "body", MUTED, (842, 240))
            return
        if not programs:
            warning = online_epg_feed_warning(channel)
            if warning:
                self._text("GUIDE WITHHELD", "body", PINK, (842, 240))
                self._wrap(warning, (842, 278), 325, MUTED)
            else:
                self._text("NO GUIDE DATA", "body", MUTED, (842, 240))
            return
        now = int(time.time())
        current_index = next(
            (index for index, program in enumerate(programs)
             if int(program.get("start", 0)) <= now < int(program.get("stop", 0))),
            0,
        )
        for row, program in enumerate(programs[current_index:current_index + 2]):
            y = 235 + row * 145
            label = "NOW" if row == 0 else "NEXT"
            start = int(program.get("start", 0))
            stop = int(program.get("stop", 0))
            times = ""
            if start:
                eastern = ZoneInfo("America/New_York")
                times = datetime.fromtimestamp(start, eastern).strftime("%I:%M %p").lstrip("0")
                if stop:
                    times += " - " + datetime.fromtimestamp(stop, eastern).strftime("%I:%M %p").lstrip("0")
            self._text(f"{label}  {times}", "small", GREEN if row == 0 else PURPLE, (842, y))
            self._wrap(str(program.get("title", "UNTITLED"))[:90], (842, y + 25), 325, WHITE)
            description = str(program.get("description", ""))
            if description:
                self._wrap(description[:150], (842, y + 72), 325, MUTED)

    def _request_tv_epg(self, channel: dict[str, str]) -> list[dict[str, Any]] | None:
        source = self.tv_active_source
        stream_id = str(channel.get("stream_id", ""))
        if not source or str(source.get("type", "")).casefold() != "xtream" or not stream_id:
            return []
        cached = self.tv_epg_cache.get(stream_id)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        if stream_id not in self.tv_epg_pending:
            self.tv_epg_pending.add(stream_id)
            threading.Thread(
                target=self._load_tv_epg,
                args=(dict(source), stream_id),
                daemon=True,
            ).start()
        return None

    def _load_tv_epg(self, source: dict[str, Any], stream_id: str) -> None:
        try:
            channel = next(
                (item for item in self.tv_channels if str(item.get("stream_id", "")) == stream_id),
                {},
            )
            programs = fetch_xtream_xmltv_epg(source, channel, TV_CACHE_ROOT, limit=4) if channel else []
            if not programs:
                programs = fetch_xtream_short_epg(source, stream_id, limit=4)
            if not programs:
                if channel and str(channel.get("group", "")).startswith("LIVE / US"):
                    programs = fetch_us_online_epg(channel, TV_CACHE_ROOT)
        except (OSError, TypeError, ValueError):
            programs = []
        self.tv_epg_cache[stream_id] = (time.time(), programs)
        self.tv_epg_pending.discard(stream_id)

    def _draw_tv_vod_gallery(self, channels: list[dict[str, str]]) -> None:
        page_size = 8
        selected = min(self.overlay_selection, max(0, len(channels) - 1))
        start = (selected // page_size) * page_size if channels else 0
        for offset, channel in enumerate(channels[start:start + page_size]):
            index = start + offset
            column, row = offset % 4, offset // 4
            x, y = 92 + column * 275, 170 + row * 205
            chosen = index == self.overlay_selection
            pygame.draw.rect(self.canvas, (13, 17, 43), (x, y, 245, 180), border_radius=10)
            pygame.draw.rect(self.canvas, PINK if chosen else CYAN, (x, y, 245, 180), 3 if chosen else 1, border_radius=10)
            artwork = self._tv_artwork_path(channel)
            self._draw_cover({"cover_path": str(artwork) if artwork else ""}, (x + 12, y + 12, 82, 116))
            self._wrap(str(channel.get("name", "UNKNOWN"))[:46], (x + 105, y + 17), 125, WHITE)
            self._text("A  PLAY", "small", GREEN, (x + 105, y + 142))
        self._draw_gallery_back(len(channels))

    def _tv_artwork_path(self, channel: dict[str, str]) -> Path | None:
        url = str(channel.get("logo", "")).strip()
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        digest = hashlib.sha256(url.encode("utf-8", errors="replace")).hexdigest()
        target = TV_ARTWORK_ROOT / f"{digest}.img"
        if target.is_file() and target.stat().st_size > 0:
            return target
        if url not in self.tv_artwork_pending and len(self.tv_artwork_pending) < 12:
            self.tv_artwork_pending.add(url)
            threading.Thread(target=self._download_tv_artwork, args=(url, target), daemon=True).start()
        return None

    def _download_tv_artwork(self, url: str, target: Path) -> None:
        temporary = target.with_suffix(".part")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "PulseArc-TV/1.0", "Accept": "image/*"})
            with urllib.request.urlopen(request, timeout=8) as response:
                data = response.read(6 * 1024 * 1024 + 1)
            if not data or len(data) > 6 * 1024 * 1024:
                return
            if not (data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8\xff") or data.startswith(b"RIFF")):
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(data)
            temporary.replace(target)
        except (OSError, ValueError):
            temporary.unlink(missing_ok=True)
        finally:
            self.tv_artwork_pending.discard(url)

    def _draw_tv_sources(self) -> None:
        sources = self._tv_sources()
        items = [
            *(public_source_label(source) for source in sources),
            "IMPORT SOURCES FROM USB / SD",
            "REFRESH ALL SOURCES",
            "BACK",
        ]
        self._text("A OPEN / REFRESH  •  X DELETE PRIVATE SOURCE", "body", MUTED, (95, 140))
        visible_rows = 7
        start = max(0, min(self.overlay_selection - visible_rows + 1, len(items) - visible_rows))
        for row, title in enumerate(items[start:start + visible_rows]):
            index = start + row
            y = 180 + row * 58
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 48), 2)
            self._text(str(title)[:88], "body", WHITE, (105, y + 12))
        self._text("USB: PulseArc/TV/sources.json or PulseArc/TV/*.m3u", "small", GREEN, (105, 605))

    def _draw_dvr(self) -> None:
        recordings = self._dvr_recordings()
        self._text(f"SAVED IPTV RECORDINGS  •  {len(recordings)}", "body", MUTED, (95, 140))
        items = [*(path.stem for path in recordings), "BACK"]
        visible_rows = 7
        start = max(0, min(self.overlay_selection - visible_rows + 1, len(items) - visible_rows))
        for row, title in enumerate(items[start:start + visible_rows]):
            index = start + row
            y = 180 + row * 58
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 48), 2)
            if index < len(recordings):
                size = recordings[index].stat().st_size / (1024 * 1024)
                title = f"{title}  •  {size:.1f} MB"
            self._text(str(title)[:88], "body", WHITE, (105, y + 12))
        self._text("A PLAY  •  X DELETE", "small", GREEN, (105, 605))

    def _draw_wifi(self) -> None:
        items = [
            *(
                f"{'CONNECTED  |  ' if item.get('active') else ''}{item.get('ssid', 'NETWORK')}"
                f"  |  {item.get('signal', 0)}%  |  {item.get('security', 'OPEN')}"
                for item in self.wifi_entries
            ),
            "SCAN AGAIN",
            "BACK",
        ]
        self._text("WI-FI NETWORKS  |  A CONNECT  |  X SCAN", "body", MUTED, (95, 140))
        visible_rows = 8
        start = max(0, min(self.overlay_selection - visible_rows + 1, len(items) - visible_rows))
        for row, title in enumerate(items[start:start + visible_rows]):
            index = start + row
            y = 172 + row * 52
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 43), 2)
            connected = index < len(self.wifi_entries) and self.wifi_entries[index].get("active")
            self._text(str(title)[:88], "body", GREEN if connected else WHITE, (105, y + 9))

    def _draw_wifi_password(self) -> None:
        self._text(f"WI-FI PASSWORD  |  {self.wifi_target[:52]}", "body", MUTED, (95, 128))
        masked = "*" * len(self.wifi_password)
        pygame.draw.rect(self.canvas, (13, 17, 43), (95, 158, 1070, 44), border_radius=6)
        pygame.draw.rect(self.canvas, CYAN, (95, 158, 1070, 44), 2, border_radius=6)
        self._text(masked[-80:] or "PASSWORD", "body", WHITE if masked else DISABLED, (110, 168))
        cell_width, cell_height = 105, 48
        for index, key in enumerate(ONSCREEN_KEYS):
            column, row = index % ONSCREEN_COLUMNS, index // ONSCREEN_COLUMNS
            x, y = 100 + column * cell_width, 220 + row * cell_height
            chosen = index == self.overlay_selection
            pygame.draw.rect(self.canvas, PINK if chosen else CYAN, (x, y, cell_width - 7, 40), 3 if chosen else 1, border_radius=5)
            label = "DEL" if key == "BACKSPACE" else key
            font = "small" if len(label) > 3 else "body"
            rendered = self.fonts[font].render(label, True, WHITE)
            self.canvas.blit(rendered, rendered.get_rect(center=(x + (cell_width - 7) // 2, y + 20)))
        self._text("A TYPE  |  X DELETE  |  PHYSICAL KEYBOARD ALSO SUPPORTED", "small", GREEN, (105, 615))

    def _draw_bluetooth(self) -> None:
        items = [
            *(
                f"{item.get('name', 'DEVICE')}  |  "
                f"{'CONNECTED' if item.get('connected') else ('PAIRED' if item.get('paired') else 'READY TO PAIR')}"
                for item in self.bluetooth_entries
            ),
            "SCAN AGAIN",
            "BACK",
        ]
        self._text("BLUETOOTH  |  PUT CONTROLLER IN PAIRING MODE  |  X SCAN", "body", MUTED, (95, 140))
        visible_rows = 8
        start = max(0, min(self.overlay_selection - visible_rows + 1, len(items) - visible_rows))
        for row, title in enumerate(items[start:start + visible_rows]):
            index = start + row
            y = 172 + row * 52
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 43), 2)
            connected = index < len(self.bluetooth_entries) and self.bluetooth_entries[index].get("connected")
            self._text(str(title)[:88], "body", GREEN if connected else WHITE, (105, y + 9))
        self._text("A PAIR / CONNECT  |  RB/R1 DISCONNECT  |  B BACK", "small", GREEN, (105, 605))

    def _draw_saves(self) -> None:
        rows = self._manager_data("saves")
        installed = {
            str(item.get("content_id", "")): item
            for item in self.library
            if is_installed_game(item)
        }
        if not rows:
            self._text("No game saves exist for this profile yet.", "body", WHITE, (95, 165))
            return
        for index, value in enumerate(rows[:6]):
            y = 145 + index * 72
            content_id = str(value.get("content_id", ""))
            entry = installed.get(content_id, {"content_id": content_id})
            self._draw_cover(entry, (105, y, 48, 62))
            self._text(str(value.get("title", "Unknown")), "body", WHITE, (175, y + 8))
            self._text(f"{int(value.get('size', 0)) / 1048576:.2f} MB", "small", MUTED, (175, y + 38))

    def _draw_settings(self) -> None:
        desktop = pygame.display.get_desktop_sizes()[0] if pygame.display.get_desktop_sizes() else LOGICAL_SIZE
        graphics = read_json(GRAPHICS_PATH, {})
        values = (
            f"DISPLAY POLICY       {str(self.settings.get('display_policy', 'auto')).upper()} ({desktop[0]}×{desktop[1]} OUTPUT)",
            f"AUDIO OUTPUT         {str(self.settings.get('audio_policy', 'hdmi')).upper()}",
            f"MASTER VOLUME        {int(self.settings.get('master_volume', 100))}%",
            f"MENU SOUNDS          {'ON' if self.settings.get('menu_sounds', True) else 'OFF'}",
            f"ARTWORK DOWNLOADS    {'ON' if self.settings.get('artwork_downloads', True) else 'OFF'}",
            f"START SCREEN         {'3D PLAZA' if self.settings.get('start_screen') == '3d-library' else 'MAIN MENU'}",
            "RUNTIME SETTINGS     INTERNAL RESOLUTION",
            f"CONTROLLER TEST      {len(self.controllers)} CONNECTED",
            "BACK",
        )
        for index, title in enumerate(values):
            y = 132 + index * 55
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 45), 2)
            self._text(title, "body", WHITE, (105, y + 11))
        self._text(
            f"Renderer: {graphics.get('session_backend', 'x11')} / {graphics.get('windows_renderer', 'auto')}  •  Network: {self.address}",
            "small",
            MUTED,
            (105, 640),
        )

    def _draw_runtime_settings(self) -> None:
        runtime = self.settings.get("runtime_resolution", {})
        scale = str(runtime.get("nintendo-64", "2x")) if isinstance(runtime, dict) else "2x"
        values = (f"NINTENDO 64          {scale.upper()}", "BACK")
        for index, title in enumerate(values):
            y = 175 + index * 64
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 52), 2)
            self._text(title, "menu", WHITE, (105, y + 12))
        self._text("A cycles 1x / 2x / 3x / 4x. Applied on the next game launch.", "small", MUTED, (105, 340))

    def _draw_simple_menu(self, values: tuple[str, ...], hint: str = "") -> None:
        visible_rows = 7
        start = max(0, min(self.overlay_selection - visible_rows + 1, len(values) - visible_rows))
        for row, title in enumerate(values[start:start + visible_rows]):
            index = start + row
            y = 155 + row * 58
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 48), 2, border_radius=7)
            self._text(title, "menu", WHITE, (105, y + 10))
        if hint:
            self._text(hint, "small", MUTED, (105, 575))
        if len(values) > visible_rows:
            page = min(len(values), self.overlay_selection + 1)
            self._text(f"{page} / {len(values)}", "small", GREEN, (1090, 575))

    def _draw_download_archives(self) -> None:
        rows = [item.path.name for item in self.download_archives]
        rows.extend(("REFRESH MEDIA", "BACK"))
        visible = 7
        start = max(0, min(self.overlay_selection - visible + 1, len(rows) - visible))
        for row, title in enumerate(rows[start:start + visible]):
            index = start + row
            y = 145 + row * 60
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 50), 2, border_radius=7)
            self._text(title[:74], "body", WHITE, (105, y + 8))
            if index < len(self.download_archives):
                item = self.download_archives[index]
                details = f"{item.source}  â€¢  {item.size / 1048576:.1f} MB  â€¢  A VALIDATE + INSTALL"
                self._text(details, "small", MUTED, (105, y + 32))
        self._text("PROTECTED VIEW: DOWNLOADS + USB/SD ONLY; ARCHIVES EXTRACT INTO ISOLATED STAGING", "small", GREEN, (105, 585))
        if len(rows) > visible:
            self._text(f"{self.overlay_selection + 1} / {len(rows)}", "small", GREEN, (1090, 610))

    @staticmethod
    def _bios_present(requirement: tuple[str, str, str, tuple[str, ...]]) -> bool:
        _label, _display, folder, names = requirement
        if folder == "ps3":
            shared = Path.home() / ".local/share/pulsearc/rpcs3-shared/rpcs3/dev_flash"
            return shared.is_dir() and sum(1 for _ in shared.rglob("*")) >= 1000
        if folder == "ps3-keys":
            candidates = (
                Path("/var/lib/pulsearc/firmware/ps3/keys"),
                Path.home() / ".local/share/pulsearc/rpcs3-keys",
            )
            return any(any(root.glob("*.key")) or any(root.glob("*.dkey")) for root in candidates if root.is_dir())
        root = Path("/var/lib/pulsearc/firmware") / folder
        return any((root / name).is_file() for name in names)

    def _draw_bios_manager(self) -> None:
        rows = [
            f"{label:<20} {'PRESENT' if self._bios_present(item) else 'MISSING'}  •  {display}"
            for item in BIOS_REQUIREMENTS
            for label, display, _folder, _names in (item,)
        ]
        rows.append("BACK")
        visible = 8
        start = max(0, min(self.overlay_selection - visible + 1, len(rows) - visible))
        for row, title in enumerate(rows[start:start + visible]):
            index = start + row
            y = 138 + row * 56
            if index == self.overlay_selection:
                pygame.draw.rect(self.canvas, PINK, (90, y, 1080, 46), 2)
            present = index < len(BIOS_REQUIREMENTS) and self._bios_present(BIOS_REQUIREMENTS[index])
            self._text(title, "body", GREEN if present else WHITE, (105, y + 11))
        self._text("A imports the selected missing file from connected USB/SD. Imported firmware stays private.", "small", MUTED, (105, 605))

    def _import_bios(self, requirement: tuple[str, str, str, tuple[str, ...]]) -> None:
        label, _display, folder, names = requirement
        if self._bios_present(requirement):
            self.status = f"{label} FIRMWARE IS ALREADY PRESENT"
            return
        files = [path for path in REMOVABLE_ROOT.rglob("*") if path.is_file()]
        source: Path | None = None
        if folder == "ps3-keys":
            source = next((
                path for path in files
                if path.suffix.casefold() == ".zip"
                and "key" in path.name.casefold()
                and ("ps3" in path.name.casefold() or "playstation 3" in path.name.casefold())
            ), None)
        else:
            wanted = {name.casefold() for name in names}
            source = next((path for path in files if path.name.casefold() in wanted), None)
        if source is None:
            self.status = f"{label}: REQUIRED FILE NOT FOUND ON USB/SD"
            return
        firmware = Path("/var/lib/pulsearc/firmware")
        try:
            if folder == "ps3-keys":
                destination = firmware / "ps3/keys"
                destination.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(source) as archive:
                    for item in archive.infolist():
                        if item.is_dir() or Path(item.filename).suffix.casefold() not in {".key", ".dkey"}:
                            continue
                        (destination / Path(item.filename).name).write_bytes(archive.read(item))
            else:
                destination = firmware / folder / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(destination.suffix + ".tmp")
                shutil.copy2(source, temporary)
                if temporary.stat().st_size < 32:
                    temporary.unlink(missing_ok=True)
                    raise ValueError("file is empty or too small")
                temporary.replace(destination)
                if folder == "ps3":
                    runner = Path.home() / ".local/share/pulsearc/runners/rpcs3/rpcs3.AppImage"
                    shared = Path.home() / ".local/share/pulsearc/rpcs3-shared"
                    if not runner.is_file():
                        raise ValueError("install the RPCS3 runtime before importing PS3 firmware")
                    self.status = "INSTALLING PLAYSTATION 3 FIRMWARE…"
                    self._draw()
                    pygame.display.flip()
                    result = subprocess.run(
                        [str(runner), "--headless", "--installfw", str(destination)],
                        check=False,
                        env={**os.environ, "APPIMAGE_EXTRACT_AND_RUN": "1", "XDG_CONFIG_HOME": str(shared)},
                        timeout=600,
                    )
                    installed = shared / "rpcs3/dev_flash"
                    if result.returncode and not installed.is_dir():
                        raise ValueError(f"RPCS3 firmware installer exited {result.returncode}")
            self.status = f"IMPORTED {label} FIRMWARE"
        except (OSError, ValueError, zipfile.BadZipFile, subprocess.TimeoutExpired) as exc:
            self.status = f"BIOS IMPORT FAILED: {exc}"

    def _draw_lines(self, lines: tuple[str, ...]) -> None:
        for index, line in enumerate(lines):
            self._wrap(line, (105, 165 + index * 58), 1050, WHITE)

    def _manager_data(self, manager: str) -> list[Any]:
        if manager not in ("saves", "cheats"):
            return []
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pulsearc.control", "manager-json", manager, "--profile", self.profile_id],
                capture_output=True,
                text=True,
                timeout=4,
                env=pulsearc_control_env(),
            )
            values = json.loads(result.stdout or "[]")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return []
        installed = {
            str(item.get("content_id", "")): item
            for item in self.library
            if is_installed_game(item)
        }
        if manager == "saves":
            rows: list[dict[str, Any]] = []
            for value in values:
                content_id = str(value.get("content_id", ""))
                entry = installed.get(content_id)
                if entry is None:
                    continue
                rows.append({
                    **value,
                    "title": str(entry.get("title", value.get("title", "Unknown"))),
                })
            return rows
        lines: list[str] = []
        for value in values[:7]:
            content_id = str(value.get("content_id", ""))
            entry = installed.get(content_id)
            if entry is None:
                continue
            lines.append(
                f"{value.get('title', entry.get('title', 'Unknown'))} [{str(value.get('platform', entry.get('platform', 'unknown'))).upper()}]"
                f"  •  {value.get('cheat_count', 0)} cheats / {value.get('enabled_count', 0)} enabled"
            )
        return lines

    def _cheat_games(self) -> list[dict[str, Any]]:
        return self.cheat_games_cache

    def _cheat_systems(self) -> list[tuple[str, int, int]]:
        grouped: dict[str, tuple[int, int]] = {}
        for game in self._cheat_games():
            platform = str(game.get("platform", "unknown"))
            games, codes = grouped.get(platform, (0, 0))
            grouped[platform] = (games + 1, codes + int(game.get("cheat_count", 0)))
        return [
            (platform, counts[0], counts[1])
            for platform, counts in sorted(grouped.items(), key=lambda item: self._system_label(item[0]))
        ]

    def _cheat_games_for_system(self) -> list[dict[str, Any]]:
        return [
            game for game in self._cheat_games()
            if str(game.get("platform", "unknown")) == self.cheat_system
        ]

    @staticmethod
    def _system_label(platform: str) -> str:
        labels = {
            "nes": "NINTENDO NES",
            "snes": "SUPER NINTENDO",
            "genesis": "SEGA GENESIS",
            "nintendo-64": "NINTENDO 64",
            "playstation": "PLAYSTATION",
            "playstation-2": "PLAYSTATION 2",
            "playstation-3": "PLAYSTATION 3",
            "wii": "NINTENDO WII",
            "wii-u": "NINTENDO WII U",
        }
        return labels.get(platform, platform.replace("-", " ").upper())

    def _query_cheat_games(self) -> list[dict[str, Any]]:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pulsearc.control", "manager-json", "cheats",
                 "--profile", self.profile_id],
                capture_output=True, text=True, timeout=4,
                env=pulsearc_control_env(),
            )
            result.check_returncode()
            values = json.loads(result.stdout or "[]")
        except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            self.status = f"CHEAT DATABASE COULD NOT BE READ: {exc}"
            return []
        installed = {
            str(item.get("content_id", "")): item
            for item in self.library if is_installed_game(item)
        }
        rows: list[dict[str, Any]] = []
        for value in values if isinstance(values, list) else []:
            content_id = str(value.get("content_id", ""))
            entry = installed.get(content_id)
            if int(value.get("cheat_count", 0)) <= 0:
                continue
            rows.append({
                **(entry or {}),
                **value,
                "title": str((entry or {}).get("title", value.get("title", "Unknown"))),
            })
        if not rows:
            self.status = "NO CHEAT CODES ARE AVAILABLE FOR THE INSTALLED GAMES"
        return rows

    def _cheat_entries(self) -> list[dict[str, Any]]:
        return self.cheat_entries_cache

    def _query_cheat_entries(self) -> list[dict[str, Any]]:
        if not self.cheat_content_id:
            return []
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pulsearc.control", "cheat-json", self.cheat_content_id,
                 "--profile", self.profile_id],
                capture_output=True, text=True, timeout=4,
                env=pulsearc_control_env(),
            )
            result.check_returncode()
            values = json.loads(result.stdout or "[]")
            return values if isinstance(values, list) else []
        except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            self.status = f"CHEAT LIST COULD NOT BE READ: {exc}"
            return []

    def _toggle_selected_cheat(self, index: int) -> None:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pulsearc.control", "cheat-toggle", self.cheat_content_id,
                 str(index), "--profile", self.profile_id],
                capture_output=True, text=True, timeout=4,
                env=pulsearc_control_env(),
            )
            result.check_returncode()
            changed = json.loads(result.stdout)
            state = "ENABLED" if changed.get("enabled") else "DISABLED"
            self.status = f"{changed.get('name', 'CHEAT')} {state}"
            self.cheat_entries_cache = self._query_cheat_entries()
            self.cheat_games_cache = self._query_cheat_games()
        except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            self.status = "CHEAT SETTING COULD NOT BE SAVED"

    def _draw_cheat_systems(self) -> None:
        systems = self._cheat_systems()
        self._text("Choose a system folder", "body", MUTED, (95, 140))
        page_size = 8
        selected = min(self.overlay_selection, max(0, len(systems) - 1))
        start = (selected // page_size) * page_size if systems else 0
        for offset, (platform, games, codes) in enumerate(systems[start:start + page_size]):
            index = start + offset
            column, row = offset % 4, offset // 4
            x, y = 92 + column * 275, 180 + row * 190
            selected_tile = index == self.overlay_selection
            color = PINK if selected_tile else CYAN
            pygame.draw.rect(self.canvas, (13, 17, 43), (x, y, 245, 155), border_radius=10)
            pygame.draw.rect(self.canvas, color, (x, y, 245, 155), 3 if selected_tile else 1, border_radius=10)
            pygame.draw.rect(self.canvas, (32, 41, 84), (x + 22, y + 29, 82, 65), border_radius=5)
            pygame.draw.rect(self.canvas, color, (x + 33, y + 18, 42, 18), border_radius=4)
            self._text(self._system_label(platform)[:22], "body", WHITE, (x + 18, y + 108))
            self._text(f"{games} GAMES  /  {codes} CODES", "small", GREEN, (x + 18, y + 135))
        self._draw_gallery_back(len(systems))

    def _draw_cheat_games(self) -> None:
        games = self._cheat_games_for_system()
        self._text(f"{self._system_label(self.cheat_system)}  /  CHOOSE A GAME", "body", MUTED, (95, 140))
        page_size = 8
        selected = min(self.overlay_selection, max(0, len(games) - 1))
        start = (selected // page_size) * page_size if games else 0
        for offset, value in enumerate(games[start:start + page_size]):
            index = start + offset
            column, row = offset % 4, offset // 4
            x, y = 92 + column * 275, 170 + row * 205
            selected_tile = index == self.overlay_selection
            pygame.draw.rect(self.canvas, (13, 17, 43), (x, y, 245, 180), border_radius=10)
            pygame.draw.rect(self.canvas, PINK if selected_tile else CYAN, (x, y, 245, 180), 3 if selected_tile else 1, border_radius=10)
            self._draw_cover(value, (x + 12, y + 12, 82, 116))
            self._wrap(str(value.get("title", "Unknown"))[:46], (x + 105, y + 17), 125, WHITE)
            self._text(f"{value.get('enabled_count', 0)} / {value.get('cheat_count', 0)} ON", "small", GREEN, (x + 105, y + 129))
            self._text("A  OPEN", "small", MUTED, (x + 105, y + 151))
        self._draw_gallery_back(len(games))

    def _draw_gallery_back(self, item_count: int) -> None:
        selected = self.overlay_selection == item_count
        pygame.draw.rect(self.canvas, CYAN if selected else (42, 48, 78), (90, 584, 1080, 44), 3 if selected else 1, border_radius=8)
        self._text("B  BACK", "body", WHITE if selected else MUTED, (105, 595))

    def _draw_cheat_details(self) -> None:
        cheats = self._cheat_entries()
        title = next(
            (str(item.get("title", "Game")) for item in self._cheat_games()
             if str(item.get("content_id", "")) == self.cheat_content_id),
            "Game",
        )
        self._text(f"{title}  /  A TOGGLE", "body", MUTED, (95, 140))
        page_size = 8
        selected = min(self.overlay_selection, max(0, len(cheats) - 1))
        start = (selected // page_size) * page_size if cheats else 0
        for offset, value in enumerate(cheats[start:start + page_size]):
            index = start + offset
            column, row = offset % 2, offset // 2
            x, y = 90 + column * 550, 175 + row * 92
            chosen = index == self.overlay_selection
            pygame.draw.rect(self.canvas, (13, 17, 43), (x, y, 520, 78), border_radius=8)
            pygame.draw.rect(self.canvas, PINK if chosen else (52, 64, 105), (x, y, 520, 78), 3 if chosen else 1, border_radius=8)
            state = "ON" if value.get("enabled") else "OFF"
            color = GREEN if value.get("enabled") else MUTED
            self._text(f"[{state}]", "body", color, (x + 14, y + 13))
            self._wrap(str(value.get("name", "Unnamed cheat"))[:75], (x + 78, y + 10), 425, WHITE)
            self._text(f"CODE {index + 1} OF {len(cheats)}", "small", MUTED, (x + 14, y + 54))
        self._draw_gallery_back(len(cheats))

    def _wrap(self, text: str, pos: tuple[int, int], width: int, color: tuple[int, int, int]) -> None:
        words = text.split()
        line = ""
        y = pos[1]
        for word in words:
            candidate = f"{line} {word}".strip()
            if self.fonts["body"].size(candidate)[0] > width and line:
                self._text(line, "body", color, (pos[0], y))
                y += 28
                line = word
            else:
                line = candidate
        if line:
            self._text(line, "body", color, (pos[0], y))


def main() -> int:
    try:
        if "--self-test" in sys.argv:
            os.environ["SDL_VIDEODRIVER"] = "dummy"
            os.environ["SDL_AUDIODRIVER"] = "dummy"
            ui = PulseArcUI(self_test=True)
            ui.boot_finished = True
            ui._button(0, True)
            ui._button(0, False)
            ui._draw()
            ui.library = [{
                "content_id": "self-test-game",
                "title": "Self Test Game",
                "platform": "nintendo-64",
                "media_kind": "rom",
                "path": "/var/lib/pulsearc/library/games/nintendo-64/test.z64",
                "source_root": "/var/lib/pulsearc/library",
            }]
            ui._open("library")
            assert ui._library_systems() == [("nintendo-64", 1)]
            ui._draw()
            ui._accept()
            assert ui.screen_name == "library-games"
            ui._draw()
            ui._open("3d-library")
            ui._draw()
            ui.store_detail_index = 0
            ui._open("3d-details")
            ui._draw()
            pygame.quit()
            print("PULSEARC_NATIVE_UI_SELF_TEST_OK")
            return 0
        return PulseArcUI().run()
    except KeyboardInterrupt:
        return 0

    def _check_or_apply_update(self) -> None:
        pending = str(getattr(self, "pending_update_version", ""))
        try:
            if pending:
                result = subprocess.run(
                    ["/usr/bin/sudo", "-n", "/usr/local/sbin/pulsearc-update", "--apply"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=180.0,
                )
                payload = json.loads((result.stdout or "{}").strip().splitlines()[-1])
                if result.returncode != 0 or payload.get("error"):
                    self.status = f"UPDATE FAILED AND ROLLED BACK: {payload.get('error', result.stderr)[-100:]}"
                    self.pending_update_version = ""
                    return
                self.status = f"UPDATED TO {str(payload.get('version', pending)).upper()}"
                self.pending_update_version = ""
                self.exit_status = 75
                self.running = False
                return

            result = subprocess.run(
                ["/usr/local/sbin/pulsearc-update", "--check"],
                check=False,
                capture_output=True,
                text=True,
                timeout=15.0,
            )
            payload = json.loads((result.stdout or "{}").strip().splitlines()[-1])
            if result.returncode != 0 or payload.get("error"):
                self.status = f"UPDATE CHECK FAILED: {payload.get('error', result.stderr)[-110:]}"
            elif payload.get("available"):
                self.pending_update_version = str(payload.get("version", "UPDATE"))
                self.status = f"{self.pending_update_version.upper()} AVAILABLE  •  PRESS A AGAIN TO INSTALL"
            else:
                self.status = f"PULSEARC {str(payload.get('current_version', 'CURRENT')).upper()} IS UP TO DATE"
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, IndexError) as exc:
            self.status = f"UPDATE CHECK FAILED: {str(exc)[-110:]}"


if __name__ == "__main__":
    raise SystemExit(main())
