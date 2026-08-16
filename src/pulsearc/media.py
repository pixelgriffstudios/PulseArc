from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Detection:
    platform: str
    runner: str
    media_kind: str
    confidence: str
    reason: str


ROM_EXTENSIONS: dict[str, tuple[str, str]] = {
    ".nes": ("nes", "retroarch:mesen"),
    ".fds": ("nes", "retroarch:mesen"),
    ".sfc": ("snes", "retroarch:snes9x"),
    ".smc": ("snes", "retroarch:snes9x"),
    ".gb": ("gameboy", "retroarch:mgba"),
    ".gbc": ("gameboy-color", "retroarch:mgba"),
    ".gba": ("gameboy-advance", "retroarch:mgba"),
    ".nds": ("nintendo-ds", "retroarch:melonds"),
    ".3ds": ("nintendo-3ds", "azahar"),
    ".cci": ("nintendo-3ds", "azahar"),
    ".cxi": ("nintendo-3ds", "azahar"),
    ".z64": ("nintendo-64", "retroarch:mupen64plus-next"),
    ".n64": ("nintendo-64", "retroarch:mupen64plus-next"),
    ".v64": ("nintendo-64", "retroarch:mupen64plus-next"),
    ".sms": ("master-system", "retroarch:genesis-plus-gx"),
    ".gg": ("game-gear", "retroarch:genesis-plus-gx"),
    ".md": ("mega-drive", "retroarch:genesis-plus-gx"),
    ".gen": ("mega-drive", "retroarch:genesis-plus-gx"),
    ".32x": ("sega-32x", "retroarch:picodrive"),
    ".pce": ("pc-engine", "retroarch:beetle-pce"),
    ".a26": ("atari-2600", "retroarch:stella"),
    ".a78": ("atari-7800", "retroarch:prosystem"),
    ".lnx": ("atari-lynx", "retroarch:handy"),
    ".j64": ("atari-jaguar", "retroarch:virtualjaguar"),
    ".jag": ("atari-jaguar", "retroarch:virtualjaguar"),
    ".d64": ("commodore-64", "retroarch:vice-x64sc"),
    ".t64": ("commodore-64", "retroarch:vice-x64sc"),
    ".prg": ("commodore-64", "retroarch:vice-x64sc"),
    ".adf": ("amiga", "retroarch:puae"),
    ".adz": ("amiga", "retroarch:puae"),
    ".gcm": ("gamecube", "dolphin"),
    ".wbfs": ("wii", "dolphin"),
    ".rvz": ("dolphin-disc", "dolphin"),
    ".wud": ("wii-u", "cemu"),
    ".wux": ("wii-u", "cemu"),
    ".cso": ("psp", "ppsspp"),
    ".vpk": ("playstation-vita", "vita3k"),
}

MEDIA_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".mpg",
    ".mpeg", ".ts", ".m2ts", ".mp3", ".wav", ".flac", ".ogg",
    ".opus", ".m4a", ".aac",
}


def _read(path: Path, offset: int, size: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read(size)


def _detect_pbp(path: Path) -> Detection:
    header = _read(path, 0, 40)
    if len(header) != 40 or header[:4] != b"\x00PBP":
        return Detection("unknown", "none", "unknown", "low", "Invalid PBP header")
    offsets = struct.unpack("<8I", header[8:40])
    data_psar_offset = offsets[7]
    file_size = path.stat().st_size
    if data_psar_offset >= file_size:
        return Detection("unknown", "none", "unknown", "low", "PBP DATA.PSAR offset is outside the file")
    psar_magic = _read(path, data_psar_offset, 16)
    if psar_magic.startswith((b"PSISOIMG", b"PSTITLEIMG")):
        return Detection(
            "playstation", "duckstation", "rom", "high",
            "PBP contains a PlayStation PSAR image",
        )
    return Detection(
        "psp", "ppsspp", "rom", "medium",
        "Valid PBP without a PlayStation PSAR signature",
    )


def _detect_signature(path: Path, suffix: str) -> Detection | None:
    head = _read(path, 0, 512)
    if head.startswith(b"NES\x1a"):
        return Detection("nes", "retroarch:mesen", "rom", "high", "iNES signature")
    if head.startswith(b"CISO"):
        return Detection("psp", "ppsspp", "rom", "high", "Compressed ISO signature")
    if len(head) >= 260 and head[256:260] in (b"NCSD", b"NCCH"):
        return Detection("nintendo-3ds", "azahar", "rom", "high", "NCSD/NCCH signature")
    n64 = head[:4]
    if n64 == bytes.fromhex("80371240"):
        return Detection("nintendo-64", "retroarch:mupen64plus-next", "rom", "high", "Big-endian N64 signature")
    if n64 == bytes.fromhex("40123780"):
        return Detection("nintendo-64", "retroarch:mupen64plus-next", "rom", "high", "Little-endian N64 signature")
    if n64 == bytes.fromhex("37804012"):
        return Detection("nintendo-64", "retroarch:mupen64plus-next", "rom", "high", "Byte-swapped N64 signature")
    if suffix == ".pbp":
        return _detect_pbp(path)
    return None


def detect(path: str | os.PathLike[str]) -> Detection:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower()
    signature = _detect_signature(source, suffix)
    if signature:
        return signature
    if suffix in ROM_EXTENSIONS:
        platform, runner = ROM_EXTENSIONS[suffix]
        return Detection(platform, runner, "rom", "medium", f"Recognized {suffix} extension")
    if suffix in (".exe", ".msi"):
        return Detection("windows", "wine-ge", "windows-program", "high", "Windows executable")
    if suffix in (".cue", ".gdi", ".cdi", ".chd", ".iso", ".bin"):
        return Detection("optical-disc", "disc-resolver", "disc-image", "low", "Disc image needs content probing")
    if suffix in MEDIA_EXTENSIONS:
        kind = "music" if suffix in {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac"} else "movie"
        return Detection(kind, "mpv", kind, "medium", f"Recognized {suffix} media extension")
    return Detection("unknown", "none", "unknown", "low", "No matching extension or signature")


def stable_content_id(path: str | os.PathLike[str]) -> str:
    """Return a stable ID without reading an entire multi-gigabyte image.

    The hash includes file size and samples from the beginning, middle, and end.
    It is stable across renames while keeping removable-media scans responsive.
    """
    source = Path(path)
    size = source.stat().st_size
    digest = hashlib.sha256()
    digest.update(size.to_bytes(8, "little"))
    sample = 1024 * 1024
    positions = sorted({0, max(0, size // 2 - sample // 2), max(0, size - sample)})
    with source.open("rb") as handle:
        for position in positions:
            handle.seek(position)
            digest.update(position.to_bytes(8, "little"))
            digest.update(handle.read(sample))
    return digest.hexdigest()[:24]
