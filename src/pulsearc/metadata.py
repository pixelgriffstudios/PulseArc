from __future__ import annotations

import re
import sqlite3
import io
import json
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image


REGION_TAGS = re.compile(r"\s*[\[(](?:USA|US|Europe|Japan|World|En(?:,[A-Za-z]{2})*|Rev\s*\d+|Disc\s*\d+)[\])]", re.I)
YEAR_TAG = re.compile(r"[\[(](19\d{2}|20\d{2})[\])]", re.I)
NON_ALNUM = re.compile(r"[^a-z0-9]+")
KNOWN_CONTENT_SUFFIXES = {
    ".7z", ".a26", ".a52", ".a78", ".apk", ".bin", ".cdi", ".chd",
    ".cue", ".d64", ".dol", ".elf", ".exe", ".gb", ".gba", ".gbc",
    ".gcm", ".gen", ".iso", ".lnx", ".m3u", ".md", ".mp3", ".mp4",
    ".mkv", ".nes", ".nsp", ".pbp", ".rvz", ".sfc", ".smc", ".swf",
    ".v64", ".wav", ".wbfs", ".wia", ".wma", ".wux", ".xci", ".z64",
    ".zip",
}


def _content_stem(value: str) -> str:
    """Strip a real media suffix without eating titles such as ``Mario Bros. 3``."""
    name = Path(value).name
    suffix = Path(name).suffix.casefold()
    return name[:-len(suffix)] if suffix in KNOWN_CONTENT_SUFFIXES else name


@dataclass(frozen=True)
class MetadataResult:
    title: str
    system_id: str
    year: int | None = None
    cover_url: str | None = None


class MetadataProvider(Protocol):
    def search(self, title: str, system_id: str) -> MetadataResult | None: ...


def normalized_title(filename: str) -> str:
    title = _content_stem(filename).replace("_", " ").replace(".", " ")
    title = REGION_TAGS.sub("", title)
    return " ".join(title.split())


def title_key(value: str) -> str:
    """Return a punctuation/region-insensitive key for offline artwork maps."""
    return NON_ALNUM.sub("", normalized_title(value).casefold())


def release_year(value: str) -> int | None:
    matches = YEAR_TAG.findall(value)
    return int(matches[-1]) if matches else None


class MetadataCache:
    def __init__(self, database: Path):
        database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata ("
            "content_id TEXT PRIMARY KEY, title TEXT NOT NULL, system_id TEXT NOT NULL, "
            "year INTEGER, cover_path TEXT, source TEXT NOT NULL, manual INTEGER NOT NULL DEFAULT 0)"
        )
        self.connection.commit()

    def lookup(self, content_id: str) -> tuple[str, str, int | None, str | None, bool] | None:
        row = self.connection.execute(
            "SELECT title,system_id,year,cover_path,manual FROM metadata WHERE content_id = ?",
            (content_id,),
        ).fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1]), row[2], row[3], bool(row[4])

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "MetadataCache":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def store(self, content_id: str, result: MetadataResult, cover_path: str | None, source: str, manual: bool = False) -> None:
        current = self.connection.execute(
            "SELECT manual FROM metadata WHERE content_id = ?", (content_id,)
        ).fetchone()
        if current and current[0] and not manual:
            return
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(content_id,title,system_id,year,cover_path,source,manual) "
            "VALUES(?,?,?,?,?,?,?)",
            (content_id, result.title, result.system_id, result.year, cover_path, source, int(manual)),
        )
        self.connection.commit()


LIBRETRO_REPOSITORIES = {
    "nes": "Nintendo_-_Nintendo_Entertainment_System",
    "snes": "Nintendo_-_Super_Nintendo_Entertainment_System",
    "gameboy": "Nintendo_-_Game_Boy",
    "gameboy-color": "Nintendo_-_Game_Boy_Color",
    "gameboy-advance": "Nintendo_-_Game_Boy_Advance",
    "nintendo-64": "Nintendo_-_Nintendo_64",
    "mega-drive": "Sega_-_Mega_Drive_-_Genesis",
    "master-system": "Sega_-_Master_System_-_Mark_III",
    "game-gear": "Sega_-_Game_Gear",
    "sega-32x": "Sega_-_32X",
    "sega-cd": "Sega_-_Mega-CD_-_Sega_CD",
    "sega-saturn": "Sega_-_Saturn",
    "dreamcast": "Sega_-_Dreamcast",
    "playstation": "Sony_-_PlayStation",
    "playstation-2": "Sony_-_PlayStation_2",
    "playstation-3": "Sony_-_PlayStation_3",
    "psp": "Sony_-_PlayStation_Portable",
    "gamecube": "Nintendo_-_GameCube",
    "wii": "Nintendo_-_Wii",
    "wii-u": "Nintendo_-_Wii_U",
    "pc-engine": "NEC_-_PC_Engine_-_TurboGrafx_16",
    "atari-2600": "Atari_-_2600",
    "atari-7800": "Atari_-_7800",
    "atari-lynx": "Atari_-_Lynx",
    "atari-jaguar": "Atari_-_Jaguar",
}


SYSTEM_ID_ALIASES = {
    "famicom": "nes",
    "nintendo-entertainment-system": "nes",
    "super-famicom": "snes",
    "super-nintendo": "snes",
    "super-nintendo-entertainment-system": "snes",
    "genesis": "mega-drive",
    "megadrive": "mega-drive",
    "sega-genesis": "mega-drive",
    "n64": "nintendo-64",
    "ps1": "playstation",
    "psx": "playstation",
    "ps2": "playstation-2",
    "ps3": "playstation-3",
    "psp": "psp",
    "gc": "gamecube",
    "ngc": "gamecube",
    "wiiu": "wii-u",
}


def canonical_system_id(system_id: str) -> str:
    """Normalize common scanner/manifest aliases before platform lookup."""
    value = NON_ALNUM.sub("-", str(system_id).strip().casefold()).strip("-")
    return SYSTEM_ID_ALIASES.get(value, value)


def cover_title_candidates(value: str) -> tuple[str, ...]:
    """Return exact-to-relaxed filenames without accidentally retaining a ROM suffix."""
    stem = _content_stem(value).strip()
    regionless = " ".join(REGION_TAGS.sub("", stem).split())
    normalized = normalized_title(value)
    return tuple(dict.fromkeys(candidate for candidate in (stem, regionless, normalized) if candidate))


def libretro_cover_url(title: str, system_id: str) -> str | None:
    repository = LIBRETRO_REPOSITORIES.get(canonical_system_id(system_id))
    if repository is None:
        return None
    quoted = urllib.parse.quote(f"{title}.png", safe="")
    return f"https://raw.githubusercontent.com/libretro-thumbnails/{repository}/master/Named_Boxarts/{quoted}"


@lru_cache(maxsize=32)
def _libretro_boxart_names(system_id: str) -> tuple[str, ...]:
    """Return official thumbnail filenames for fuzzy region-tag matching."""
    system_id = canonical_system_id(system_id)
    repository = LIBRETRO_REPOSITORIES.get(system_id)
    if repository is None:
        return ()
    playlist = repository.replace("_", " ").replace(" - ", " - ")
    url = (
        "https://thumbnails.libretro.com/"
        f"{urllib.parse.quote(playlist, safe='')}/Named_Boxarts/"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "PulseArc-OS/0.0.1"})
    try:
        with urllib.request.urlopen(request, timeout=8.0) as response:
            payload = response.read(12 * 1024 * 1024 + 1)
    except (OSError, urllib.error.URLError):
        return ()
    if len(payload) > 12 * 1024 * 1024:
        return ()
    page = payload.decode("utf-8", errors="replace")
    return tuple(
        urllib.parse.unquote(value)
        for value in re.findall(r'href="([^"?#]+\.png)"', page, flags=re.I)
    )


def libretro_fuzzy_cover_url(title: str, system_id: str) -> str | None:
    """Resolve a boxart whose filename differs only by region/revision tags."""
    system_id = canonical_system_id(system_id)
    wanted = title_key(title)
    match = next(
        (name for name in _libretro_boxart_names(system_id) if title_key(Path(name).stem) == wanted),
        "",
    )
    if not match:
        return None
    repository = LIBRETRO_REPOSITORIES[system_id]
    playlist = repository.replace("_", " ").replace(" - ", " - ")
    return (
        "https://thumbnails.libretro.com/"
        f"{urllib.parse.quote(playlist, safe='')}/Named_Boxarts/"
        f"{urllib.parse.quote(match, safe='')}"
    )


def download_cover(url: str, destination: Path, timeout: float = 8.0) -> bool:
    request = urllib.request.Request(url, headers={"User-Agent": "PulseArc-OS/0.0.1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(10 * 1024 * 1024 + 1)
    except (OSError, urllib.error.URLError):
        return False
    if len(payload) > 10 * 1024 * 1024 or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_bytes(payload)
    temporary.replace(destination)
    return True


def download_image_as_png(url: str, destination: Path, timeout: float = 8.0) -> bool:
    """Download a bounded web image and normalize it to an RGB PNG."""
    request = urllib.request.Request(url, headers={"User-Agent": "PulseArc-OS/0.0.1 (artwork resolver)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(12 * 1024 * 1024 + 1)
        if len(payload) > 12 * 1024 * 1024:
            return False
        with Image.open(io.BytesIO(payload)) as image:
            image.thumbnail((900, 1200), Image.Resampling.LANCZOS)
            converted = image.convert("RGB")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(".tmp")
            converted.save(temporary, format="PNG", optimize=True)
            temporary.replace(destination)
    except (OSError, ValueError, urllib.error.URLError, Image.DecompressionBombError):
        return False
    return True


def _json_request(url: str, timeout: float = 8.0) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "PulseArc-OS/0.0.1 (artwork resolver)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("metadata response is too large")
    value = json.loads(payload.decode("utf-8"))
    return value if isinstance(value, dict) else {}


def wikipedia_cover_url(title: str, media_kind: str, timeout: float = 8.0) -> str | None:
    """Resolve a movie/show/album cover through the public MediaWiki API.

    The article search is followed by an image-info lookup because non-free
    film posters are often omitted from the pageimages thumbnail property.
    """
    cleaned = normalized_title(title)
    year = release_year(title)
    suffix = "film" if media_kind in {"movie", "video", "dvd-video"} else "album"
    search_term = " ".join(part for part in (cleaned, str(year or ""), suffix) if part)
    query = urllib.parse.urlencode({
        "action": "query",
        "generator": "search",
        "gsrsearch": search_term,
        "gsrnamespace": 0,
        "gsrlimit": 5,
        "prop": "images",
        "imlimit": 50,
        "format": "json",
        "origin": "*",
    })
    try:
        result = _json_request(f"https://en.wikipedia.org/w/api.php?{query}", timeout)
        pages = list(result.get("query", {}).get("pages", {}).values())
        pages.sort(key=lambda page: int(page.get("index", 999)))
        preferred_words = ("poster", "movie", "film", "dvd", "cover", "album")
        image_title = ""
        for page in pages:
            images = [str(item.get("title", "")) for item in page.get("images", [])]
            candidates = [name for name in images if any(word in name.casefold() for word in preferred_words)]
            candidates = [name for name in candidates if not name.lower().endswith(".svg")]
            if candidates:
                image_title = candidates[0]
                break
        if not image_title:
            return None
        image_query = urllib.parse.urlencode({
            "action": "query",
            "titles": image_title,
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": 600,
            "format": "json",
            "origin": "*",
        })
        image_result = _json_request(f"https://en.wikipedia.org/w/api.php?{image_query}", timeout)
        image_pages = image_result.get("query", {}).get("pages", {}).values()
        for page in image_pages:
            for info in page.get("imageinfo", []):
                url = str(info.get("thumburl") or info.get("url") or "")
                if url.startswith("https://"):
                    return url
    except (OSError, ValueError, TypeError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return None


def wikipedia_synopsis(title: str, media_kind: str, timeout: float = 8.0) -> str | None:
    """Resolve a concise plain-text synopsis through the MediaWiki API."""
    cleaned = normalized_title(title)
    year = release_year(title)
    if media_kind in {"movie", "video", "dvd-video"}:
        suffix = "film"
    elif media_kind in {"music", "audio"}:
        suffix = "album"
    else:
        suffix = "video game"
    search_term = " ".join(part for part in (cleaned, str(year or ""), suffix) if part)
    query = urllib.parse.urlencode({
        "action": "query",
        "generator": "search",
        "gsrsearch": search_term,
        "gsrnamespace": 0,
        "gsrlimit": 3,
        "prop": "extracts",
        "exintro": 1,
        "explaintext": 1,
        "exchars": 700,
        "format": "json",
        "origin": "*",
    })
    try:
        result = _json_request(f"https://en.wikipedia.org/w/api.php?{query}", timeout)
        pages = list(result.get("query", {}).get("pages", {}).values())
        pages.sort(key=lambda page: int(page.get("index", 999)))
        for page in pages:
            synopsis = " ".join(str(page.get("extract", "")).split())
            if len(synopsis) >= 40:
                return synopsis[:700]
    except (OSError, ValueError, TypeError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return None


def offline_cover_path(title: str, system_id: str, root: Path) -> Path | None:
    index_path = root / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    system = index.get(canonical_system_id(system_id), {}) if isinstance(index, dict) else {}
    relative = system.get(title_key(title), "") if isinstance(system, dict) else ""
    candidate = root / str(relative)
    return candidate if relative and candidate.is_file() else None
