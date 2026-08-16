from __future__ import annotations

import json
import os
import time
import hashlib
from pathlib import Path

from .metadata import (
    MetadataCache,
    MetadataResult,
    download_cover,
    download_image_as_png,
    canonical_system_id,
    cover_title_candidates,
    libretro_fuzzy_cover_url,
    libretro_cover_url,
    normalized_title,
    offline_cover_path,
    wikipedia_cover_url,
    wikipedia_synopsis,
)


INDEX = Path("/run/pulsearc/library.json")
OUTPUT = Path(os.environ.get("PULSEARC_COVERS_PATH", "/run/pulsearc/covers.json"))
SYNOPSES_OUTPUT = Path(os.environ.get("PULSEARC_SYNOPSIS_PATH", "/run/pulsearc/synopses.json"))
STATE = Path("/var/lib/pulsearc")
OFFLINE_ARTWORK = Path(os.environ.get("PULSEARC_OFFLINE_ARTWORK", "/usr/share/pulsearc/artwork/offline"))
SYNOPSIS_EXCLUDED_TITLES = {"hell on rails"}
MANUAL_SYNOPSIS_BY_TITLE = {
    "beyond the beyond": (
        "A traditional fantasy role-playing game in which the young knight Finn sets out "
        "with a band of allies to stop an ancient evil and save the kingdom of Marion."
    ),
    "speed devils": (
        "An arcade racing game featuring fictional street cars, hazardous tracks, rival "
        "drivers, traffic, shortcuts, weather, and wagers as players climb the racing rankings."
    ),
}


def mounted_dvd_entry(root: Path = Path("/run/media/gamer")) -> dict[str, str] | None:
    """Mirror the shell's temporary DVD entry for artwork resolution."""
    if not root.is_dir():
        return None
    try:
        marker = next(
            (
                path for path in root.rglob("*")
                if path.is_file() and path.name.upper() == "VIDEO_TS.IFO"
                and path.parent.name.upper() == "VIDEO_TS"
            ),
            None,
        )
    except OSError:
        return None
    if marker is None:
        return None
    raw_title = marker.parents[1].name or "DVD Movie"
    display_title = " ".join(raw_title.replace("_", " ").split()).title()
    identity = hashlib.sha256(display_title.casefold().encode("utf-8")).hexdigest()[:16]
    return {
        "content_id": f"pulsearc-dvd-video-{identity}",
        "title": display_title,
        "platform": "dvd-video",
        "media_kind": "dvd-video",
        "path": "/dev/sr0",
        "source_root": str(marker.parents[1]),
    }


def process_once(cache: MetadataCache) -> dict[str, str]:
    if not INDEX.exists():
        return {}
    try:
        entries = json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    dvd_entry = mounted_dvd_entry()
    if dvd_entry is not None:
        entries = [*entries, dvd_entry]
    covers: dict[str, str] = {}
    try:
        existing_synopses = json.loads(SYNOPSES_OUTPUT.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        existing_synopses = {}
    synopses: dict[str, str] = existing_synopses if isinstance(existing_synopses, dict) else {}
    # Keep a newly inserted multi-ROM drive from blocking artwork and UI updates
    # behind dozens of network synopsis requests. Missing summaries are filled in
    # over subsequent daemon passes.
    synopsis_lookup_budget = 2
    for entry in entries:
        content_id = str(entry.get("content_id", ""))
        if not content_id:
            continue
        raw_title = str(entry.get("title", "")).strip()
        title = normalized_title(raw_title)
        system_id = canonical_system_id(str(entry.get("platform", "unknown")))
        media_kind = str(entry.get("media_kind") or system_id).lower()
        local_synopsis = str(entry.get("synopsis", "")).strip()
        title_match = title.casefold()
        if title_match in SYNOPSIS_EXCLUDED_TITLES:
            synopses.pop(content_id, None)
        elif title_match in MANUAL_SYNOPSIS_BY_TITLE:
            synopses[content_id] = MANUAL_SYNOPSIS_BY_TITLE[title_match]
        elif local_synopsis:
            synopses[content_id] = local_synopsis
        elif content_id not in synopses and synopsis_lookup_budget > 0:
            synopsis_lookup_budget -= 1
            synopsis = wikipedia_synopsis(raw_title, media_kind)
            if synopsis:
                synopses[content_id] = synopsis
        local_cover_value = str(entry.get("cover_path", "")).strip()
        if local_cover_value:
            local_cover = Path(local_cover_value)
            if local_cover.is_file():
                covers[content_id] = str(local_cover)
                cache.store(
                    content_id,
                    MetadataResult(str(entry.get("title", "Unknown")), str(entry.get("platform", "unknown"))),
                    str(local_cover), "portable-media",
                )
                continue
        manual = STATE / "artwork" / "manual" / f"{content_id}.png"
        if manual.is_file():
            covers[content_id] = str(manual)
            cache.store(
                content_id,
                MetadataResult(str(entry.get("title", "Unknown")), str(entry.get("platform", "unknown"))),
                str(manual), "user", manual=True,
            )
            continue
        cached = cache.lookup(content_id)
        if cached and cached[3] and Path(cached[3]).is_file():
            covers[content_id] = str(cached[3])
            continue
        destination = STATE / "artwork" / "cache" / system_id / f"{content_id}.png"
        offline = offline_cover_path(raw_title, system_id, OFFLINE_ARTWORK)
        if offline is not None:
            covers[content_id] = str(offline)
            cache.store(content_id, MetadataResult(title, system_id), str(offline), "pulsearc-offline-labels")
            continue
        if media_kind in {"movie", "video", "dvd-video", "music", "audio"}:
            url = wikipedia_cover_url(raw_title, media_kind)
            if url and download_image_as_png(url, destination):
                covers[content_id] = str(destination)
                cache.store(content_id, MetadataResult(title, system_id, cover_url=url), str(destination), "wikipedia")
                continue
        # Named_Boxarts generally retains region/revision tags. Try the exact
        # scanner title before falling back to the older normalized lookup.
        for candidate in cover_title_candidates(raw_title):
            url = libretro_cover_url(candidate, system_id)
            if url and download_cover(url, destination):
                covers[content_id] = str(destination)
                cache.store(content_id, MetadataResult(title, system_id, cover_url=url), str(destination), "libretro-thumbnails")
                break
        if content_id not in covers:
            url = libretro_fuzzy_cover_url(title, system_id)
            if url and download_cover(url, destination):
                covers[content_id] = str(destination)
                cache.store(
                    content_id, MetadataResult(title, system_id, cover_url=url),
                    str(destination), "libretro-thumbnails-fuzzy",
                )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(covers, indent=2), encoding="utf-8")
    temporary.replace(OUTPUT)
    SYNOPSES_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    synopsis_temporary = SYNOPSES_OUTPUT.with_suffix(".tmp")
    synopsis_temporary.write_text(json.dumps(synopses, indent=2), encoding="utf-8")
    synopsis_temporary.replace(SYNOPSES_OUTPUT)
    return covers


def run() -> None:
    with MetadataCache(STATE / "metadata" / "library.db") as cache:
        while True:
            process_once(cache)
            time.sleep(30.0)


if __name__ == "__main__":
    run()
