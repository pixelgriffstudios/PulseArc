#!/usr/bin/env python3
"""Controller-shell helpers for PulseArc television sources.

The parser is intentionally dependency-free so the native shell can keep
working when a provider is offline or returns a malformed playlist.  Private
provider data is stored below the gamer account with owner-only permissions.
"""

from __future__ import annotations

import base64
import datetime as dt
import difflib
import gzip
import hashlib
import json
import os
import re
import shutil
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable


BUILTIN_TV_SOURCES: tuple[dict[str, str], ...] = (
    {
        "name": "IPTV-ORG / FULL USA (ALL CHANNELS)",
        "type": "m3u",
        "url": "https://iptv-org.github.io/iptv/countries/us.m3u",
        "builtin": "true",
    },
)

FREE_STREAMING_APPS: tuple[dict[str, str], ...] = (
    {"name": "TUBI", "url": "https://tubitv.com/", "note": "FREE MOVIES, SHOWS, AND LIVE TV"},
    {"name": "PLUTO TV", "url": "https://pluto.tv/", "note": "FREE LIVE CHANNELS AND ON-DEMAND TV"},
    {"name": "PLEX FREE TV", "url": "https://watch.plex.tv/", "note": "FREE LIVE TV AND MOVIES"},
    {"name": "YOUTUBE", "url": "https://www.youtube.com/tv", "note": "FREE VIDEO AND LIVE CHANNELS"},
)

EXTINF_ATTRIBUTE = re.compile(r'([\w-]+)="([^"]*)"')
US_XMLTV_URL = "https://epg.pw/xmltv/epg_US.xml.gz"
US_XMLTV_INDEX_VERSION = 2
XTREAM_XMLTV_INDEX_VERSION = 1

# The public XMLTV service has two distinct failure modes that cannot safely be
# hidden from the viewer: a small number of schedules use a bad UTC declaration,
# while some provider streams carry different programming despite retaining the
# network bug/logo.  Keep corrections deliberately narrow and prefer no listing
# over presenting a known-wrong title as "NOW".
US_XMLTV_TIME_OFFSETS = {
    "amc": -8 * 3600,
}
US_XMLTV_UNRELIABLE_CHANNELS = {
    "bbc america",
    "bet",
}
_ONLINE_EPG_MEMORY: dict[str, list[dict[str, Any]]] | None = None
_ONLINE_EPG_LOCK = threading.Lock()
_XTREAM_EPG_MEMORY: dict[str, tuple[float, dict[str, list[dict[str, Any]]]]] = {}
_XTREAM_EPG_LOCK = threading.Lock()


def _safe_text(value: Any, limit: int = 160) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:limit]


def parse_m3u(text: str, source_name: str = "PLAYLIST") -> list[dict[str, str]]:
    """Parse a standard extended M3U playlist and ignore unsafe entries."""
    channels: list[dict[str, str]] = []
    metadata: dict[str, str] | None = None
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            attributes = {key.casefold(): value for key, value in EXTINF_ATTRIBUTE.findall(line)}
            title = line.rsplit(",", 1)[-1] if "," in line else attributes.get("tvg-name", "CHANNEL")
            metadata = {
                "name": _safe_text(title, 100) or "CHANNEL",
                "group": _safe_text(attributes.get("group-title", "OTHER"), 60).upper() or "OTHER",
                "logo": _safe_text(attributes.get("tvg-logo", ""), 500),
                "channel_id": _safe_text(attributes.get("tvg-id", ""), 160),
                "source": _safe_text(source_name, 100),
            }
            continue
        if line.startswith("#"):
            continue
        parsed = urllib.parse.urlsplit(line)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            metadata = None
            continue
        values = metadata or {
            "name": _safe_text(parsed.hostname or "CHANNEL", 100),
            "group": "OTHER",
            "logo": "",
            "channel_id": "",
            "source": _safe_text(source_name, 100),
        }
        channels.append({**values, "url": line[:4096]})
        metadata = None
    return channels


def xtream_playlist_url(source: dict[str, Any]) -> str:
    """Build a conventional Xtream M3U endpoint without logging credentials."""
    server = str(source.get("server", "")).strip().rstrip("/")
    if not urllib.parse.urlsplit(server).scheme:
        server = "http://" + server
    parsed = urllib.parse.urlsplit(server)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Xtream server must be an HTTP or HTTPS address")
    port_value = str(source.get("port", "")).strip()
    port = int(port_value) if port_value else parsed.port
    if port is not None and not (1 <= port <= 65535):
        raise ValueError("Xtream port must be between 1 and 65535")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    base_path = parsed.path.rstrip("/")
    endpoint = f"{base_path}/get.php" if base_path else "/get.php"
    query = urllib.parse.urlencode({
        "username": str(source.get("username", "")),
        "password": str(source.get("password", "")),
        "type": "m3u_plus",
        "output": str(source.get("output", "ts")) or "ts",
    })
    return urllib.parse.urlunsplit((parsed.scheme, netloc, endpoint, query, ""))


def source_url(source: dict[str, Any]) -> str:
    if str(source.get("type", "m3u")).casefold() == "xtream":
        return xtream_playlist_url(source)
    url = str(source.get("url", "")).strip()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url
    raise ValueError("Playlist URL must use HTTP or HTTPS")


def _xtream_endpoint(source: dict[str, Any], endpoint: str, **parameters: Any) -> str:
    playlist = urllib.parse.urlsplit(xtream_playlist_url(source))
    query = {
        "username": str(source.get("username", "")),
        "password": str(source.get("password", "")),
        **{key: str(value) for key, value in parameters.items()},
    }
    base_path = playlist.path.rsplit("/", 1)[0]
    path = f"{base_path}/{endpoint}" if base_path else f"/{endpoint}"
    return urllib.parse.urlunsplit((playlist.scheme, playlist.netloc, path, urllib.parse.urlencode(query), ""))


def xtream_xmltv_url(source: dict[str, Any]) -> str:
    """Build the provider's authenticated XMLTV endpoint."""
    return _xtream_endpoint(source, "xmltv.php")


def _xtream_media_url(source: dict[str, Any], media_type: str, stream_id: Any, extension: str) -> str:
    playlist = urllib.parse.urlsplit(xtream_playlist_url(source))
    username = urllib.parse.quote(str(source.get("username", "")), safe="")
    password = urllib.parse.quote(str(source.get("password", "")), safe="")
    identifier = urllib.parse.quote(str(stream_id), safe="")
    suffix = re.sub(r"[^A-Za-z0-9]+", "", extension) or ("ts" if media_type == "live" else "mp4")
    base_path = playlist.path.rsplit("/", 1)[0]
    path = f"{base_path}/{media_type}/{username}/{password}/{identifier}.{suffix}"
    return urllib.parse.urlunsplit((playlist.scheme, playlist.netloc, path, "", ""))


def xtream_media_url(source: dict[str, Any], media_type: str, stream_id: Any, extension: str) -> str:
    """Public, validated media URL builder for companion PulseArc screens."""
    return _xtream_media_url(source, media_type, stream_id, extension)


def _read_json_url(url: str, timeout: float) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "PulseArc-TV/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024:
        raise ValueError("Xtream response exceeds 64 MB limit")
    return json.loads(data.decode("utf-8-sig", errors="replace"))


def _decode_epg_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        decoded = base64.b64decode(text, validate=True).decode("utf-8")
        printable = sum(character.isprintable() or character in "\r\n\t" for character in decoded)
        if decoded and printable / len(decoded) >= 0.9:
            return _safe_text(decoded, 500)
    except (ValueError, TypeError, UnicodeDecodeError):
        pass
    return _safe_text(text, 500)


def _epg_timestamp(item: dict[str, Any], *keys: str) -> int:
    for key in keys:
        try:
            value = int(float(str(item.get(key, "0"))))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0


def fetch_xtream_short_epg(
    source: dict[str, Any], stream_id: str | int, limit: int = 4, timeout: float = 12.0
) -> list[dict[str, Any]]:
    """Fetch a small Now/Next guide without downloading the provider's full XMLTV file."""
    identifier = re.sub(r"[^0-9]+", "", str(stream_id))
    if not identifier:
        return []
    payload = _read_json_url(
        _xtream_endpoint(
            source,
            "player_api.php",
            action="get_short_epg",
            stream_id=identifier,
            limit=max(1, min(12, int(limit))),
        ),
        timeout,
    )
    listings = payload.get("epg_listings", []) if isinstance(payload, dict) else []
    if not isinstance(listings, list):
        return []
    programs: list[dict[str, Any]] = []
    for item in listings:
        if not isinstance(item, dict):
            continue
        programs.append({
            "title": _decode_epg_text(item.get("title")) or "UNTITLED PROGRAM",
            "description": _decode_epg_text(item.get("description")),
            "start": _epg_timestamp(item, "start_timestamp", "start"),
            "stop": _epg_timestamp(item, "stop_timestamp", "end_timestamp", "stop", "end"),
            "source": "PROVIDER",
        })
    return programs


def _normalize_epg_channel(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", errors="ignore").decode("ascii").casefold()
    text = re.sub(r"^(?:us|usa|go|prime|rk|ca en)\s*:\s*", "", text)
    text = text.replace("pacific", "west").replace("western", "west")
    text = text.replace("eastern", "east")
    text = re.sub(r"\bmusic television\b", "mtv", text)
    text = re.sub(r"\bmtv\s*2\b", "mtv2", text)
    text = re.sub(r"\bamc\s*\+", "amc plus", text)
    text = re.sub(r"\b(?:uhd|fhd|hd|sd|4k|raw|60fps|channel|usa)\b", " ", text)
    words = re.findall(r"[a-z0-9]+", text)
    compact: list[str] = []
    for word in words:
        if not compact or compact[-1] != word:
            compact.append(word)
    return " ".join(compact)


def _xmltv_timestamp(value: Any) -> int:
    text = str(value or "").strip()
    if len(text) < 14:
        return 0
    try:
        moment = dt.datetime.strptime(text[:14], "%Y%m%d%H%M%S")
        offset = re.search(r"([+-])(\d{2})(\d{2})", text[14:])
        if offset:
            minutes = int(offset.group(2)) * 60 + int(offset.group(3))
            if offset.group(1) == "-":
                minutes = -minutes
            moment = moment.replace(tzinfo=dt.timezone(dt.timedelta(minutes=minutes)))
        else:
            moment = moment.replace(tzinfo=dt.timezone.utc)
        return int(moment.timestamp())
    except (TypeError, ValueError):
        return 0


def _download_xtream_xmltv(source: dict[str, Any], target: Path, timeout: float = 90.0) -> None:
    """Download a provider guide atomically without retaining credentials in its filename."""
    request = urllib.request.Request(
        xtream_xmltv_url(source),
        headers={"User-Agent": "PulseArc-TV/1.0", "Accept": "application/xml, text/xml"},
    )
    maximum = 256 * 1024 * 1024
    temporary = target.with_suffix(target.suffix + ".new")
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, temporary.open("wb") as output:
            length = int(response.headers.get("Content-Length", "0") or 0)
            if length > maximum:
                raise ValueError("provider guide exceeds size limit")
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > maximum:
                    raise ValueError("provider guide exceeds size limit")
                output.write(block)
        if total == 0:
            raise ValueError("provider guide download is empty")
        os.chmod(temporary, 0o600)
        temporary.replace(target)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _xmltv_child_text(element: ET.Element, wanted: str, default: str = "") -> str:
    for child in element:
        if child.tag.rsplit("}", 1)[-1] == wanted:
            return str(child.text or default)
    return default


def _build_xtream_epg_index(xmltv_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Index a full provider XMLTV guide by exact ID and normalized display name."""
    now = int(time.time())
    lower, upper = now - 6 * 3600, now + 72 * 3600
    channel_names: dict[str, set[str]] = {}
    raw_programs: dict[str, list[dict[str, Any]]] = {}
    with xmltv_path.open("rb") as stream:
        for _event, element in ET.iterparse(stream, events=("end",)):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "channel":
                identifier = str(element.get("id", "")).strip()
                names = {
                    normalized
                    for node in element
                    if node.tag.rsplit("}", 1)[-1] == "display-name"
                    and (normalized := _normalize_epg_channel(node.text))
                }
                if identifier:
                    channel_names[identifier] = names
                element.clear()
            elif tag == "programme":
                start = _xmltv_timestamp(element.get("start"))
                stop = _xmltv_timestamp(element.get("stop"))
                identifier = str(element.get("channel", "")).strip()
                if identifier and stop >= lower and start <= upper:
                    raw_programs.setdefault(identifier, []).append({
                        "title": _safe_text(_xmltv_child_text(element, "title", "UNTITLED PROGRAM"), 160)
                        or "UNTITLED PROGRAM",
                        "description": _safe_text(_xmltv_child_text(element, "desc"), 500),
                        "start": start,
                        "stop": stop,
                        "source": "PROVIDER XMLTV",
                    })
                element.clear()
    index: dict[str, list[dict[str, Any]]] = {}
    for identifier, programs in raw_programs.items():
        keys = {"id:" + identifier.casefold(), _normalize_epg_channel(identifier)}
        keys.update(channel_names.get(identifier, ()))
        unique = {(int(item["start"]), str(item["title"])): item for item in programs}
        ordered = sorted(unique.values(), key=lambda item: int(item["start"]))
        for key in keys:
            if key:
                index[key] = ordered
    return index


def _load_xtream_epg_index(
    source: dict[str, Any], cache_root: Path, timeout: float = 90.0
) -> dict[str, list[dict[str, Any]]]:
    identity = _source_identity(source)
    with _XTREAM_EPG_LOCK:
        remembered = _XTREAM_EPG_MEMORY.get(identity)
        if remembered and time.time() - remembered[0] < 6 * 3600:
            return remembered[1]
        cache_root.mkdir(parents=True, exist_ok=True)
        xmltv_path = cache_root / f"{identity}.xmltv.xml"
        index_path = cache_root / f"{identity}.xmltv-index-v{XTREAM_XMLTV_INDEX_VERSION}.json"
        try:
            if time.time() - index_path.stat().st_mtime < 6 * 3600:
                payload = json.loads(index_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and payload:
                    _XTREAM_EPG_MEMORY[identity] = (time.time(), payload)
                    return payload
        except (OSError, ValueError, TypeError):
            pass
        try:
            needs_download = time.time() - xmltv_path.stat().st_mtime >= 12 * 3600
        except OSError:
            needs_download = True
        if needs_download:
            try:
                _download_xtream_xmltv(source, xmltv_path, timeout)
            except (OSError, ValueError, urllib.error.URLError):
                if not xmltv_path.exists():
                    raise
        index = _build_xtream_epg_index(xmltv_path)
        temporary = index_path.with_suffix(".json.new")
        temporary.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(index_path)
        _XTREAM_EPG_MEMORY[identity] = (time.time(), index)
        return index


def fetch_xtream_xmltv_epg(
    source: dict[str, Any], channel: dict[str, Any], cache_root: Path,
    limit: int = 4, timeout: float = 90.0,
) -> list[dict[str, Any]]:
    """Return provider-authored Now/Next listings for one Xtream channel."""
    try:
        index = _load_xtream_epg_index(source, cache_root, timeout)
    except (OSError, ValueError, TypeError, EOFError, ET.ParseError, urllib.error.URLError):
        return []
    keys: list[str] = []
    tvg_id = str(channel.get("tvg_id") or channel.get("channel_id") or "").strip()
    if tvg_id:
        keys.append("id:" + tvg_id.casefold())
    matched = _match_epg_channel(channel, (key for key in index if not key.startswith("id:")))
    if matched:
        keys.append(matched)
    programs = next((index[key] for key in keys if key in index), [])
    now = int(time.time())
    current = next((position for position, item in enumerate(programs)
                    if int(item.get("start", 0)) <= now < int(item.get("stop", 0))), None)
    if current is None:
        current = next((position for position, item in enumerate(programs)
                        if int(item.get("start", 0)) >= now), 0)
    return [dict(item) for item in programs[current:current + max(1, min(12, int(limit)))]]


def _download_us_xmltv(target: Path, timeout: float = 45.0) -> None:
    request = urllib.request.Request(
        US_XMLTV_URL,
        headers={"User-Agent": "PulseArc-TV/1.0", "Accept": "application/gzip, application/xml"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        length = int(response.headers.get("Content-Length", "0") or 0)
        if length > 64 * 1024 * 1024:
            raise ValueError("US guide exceeds compressed size limit")
        payload = response.read(64 * 1024 * 1024 + 1)
    if not payload or len(payload) > 64 * 1024 * 1024:
        raise ValueError("US guide download is empty or oversized")
    temporary = target.with_suffix(target.suffix + ".new")
    temporary.write_bytes(payload)
    os.chmod(temporary, 0o600)
    temporary.replace(target)


def _build_us_epg_index(xmltv_path: Path) -> dict[str, list[dict[str, Any]]]:
    now = int(time.time())
    lower, upper = now - 6 * 3600, now + 48 * 3600
    channel_names: dict[str, set[str]] = {}
    raw_programs: dict[str, list[dict[str, Any]]] = {}
    with gzip.open(xmltv_path, "rb") as stream:
        for _event, element in ET.iterparse(stream, events=("end",)):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "channel":
                identifier = str(element.get("id", ""))
                names = {
                    normalized
                    for node in element.findall("./display-name")
                    if (normalized := _normalize_epg_channel(node.text))
                }
                if names:
                    channel_names[identifier] = names
                element.clear()
            elif tag == "programme":
                start = _xmltv_timestamp(element.get("start"))
                stop = _xmltv_timestamp(element.get("stop"))
                if stop >= lower and start <= upper:
                    title = element.findtext("./title", default="UNTITLED PROGRAM")
                    description = element.findtext("./desc", default="")
                    raw_programs.setdefault(str(element.get("channel", "")), []).append({
                        "title": _safe_text(title, 160) or "UNTITLED PROGRAM",
                        "description": _safe_text(description, 500),
                        "start": start,
                        "stop": stop,
                        "source": "ONLINE ET",
                    })
                element.clear()
    index: dict[str, list[dict[str, Any]]] = {}
    for identifier, programs in raw_programs.items():
        for name in channel_names.get(identifier, ()): 
            index.setdefault(name, []).extend(programs)
    for name, programs in index.items():
        unique = {(int(item["start"]), str(item["title"])): item for item in programs}
        index[name] = sorted(unique.values(), key=lambda item: int(item["start"]))
    return index


def _load_us_epg_index(cache_root: Path) -> dict[str, list[dict[str, Any]]]:
    global _ONLINE_EPG_MEMORY
    with _ONLINE_EPG_LOCK:
        if _ONLINE_EPG_MEMORY is not None:
            return _ONLINE_EPG_MEMORY
        cache_root.mkdir(parents=True, exist_ok=True)
        xmltv_path = cache_root / "us-online-epg.xml.gz"
        index_path = cache_root / f"us-online-epg-index-v{US_XMLTV_INDEX_VERSION}.json"
        try:
            if time.time() - index_path.stat().st_mtime < 6 * 3600:
                payload = json.loads(index_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict) and payload:
                    _ONLINE_EPG_MEMORY = payload
                    return payload
        except (OSError, ValueError, TypeError):
            pass
        try:
            needs_download = time.time() - xmltv_path.stat().st_mtime >= 12 * 3600
        except OSError:
            needs_download = True
        if needs_download:
            try:
                _download_us_xmltv(xmltv_path)
            except (OSError, ValueError, urllib.error.URLError):
                if not xmltv_path.exists():
                    raise
        index = _build_us_epg_index(xmltv_path)
        temporary = index_path.with_suffix(".json.new")
        temporary.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(index_path)
        _ONLINE_EPG_MEMORY = index
        return index


def _match_epg_channel(channel: dict[str, Any], names: Iterable[str]) -> str:
    requested = []
    for value in (channel.get("name"), channel.get("tvg_id"), channel.get("channel_id")):
        normalized = _normalize_epg_channel(value)
        if normalized:
            requested.append(normalized)
            if normalized.endswith(" us"):
                requested.append(normalized[:-3])
    available = list(names)
    for candidate in requested:
        if candidate in available:
            return candidate
    best_name, best_score = "", 0.0
    requested_feed = "west" if any("west" in item for item in requested) else "east" if any("east" in item for item in requested) else ""
    for candidate in requested:
        for available_name in available:
            if requested_feed and ("west" in available_name or "east" in available_name) and requested_feed not in available_name:
                continue
            score = difflib.SequenceMatcher(None, candidate, available_name).ratio()
            if score > best_score:
                best_name, best_score = available_name, score
    return best_name if best_score >= 0.82 else ""


def fetch_us_online_epg(channel: dict[str, Any], cache_root: Path) -> list[dict[str, Any]]:
    """Return online Now/Next fallback listings for a matched US channel/feed."""
    requested = {
        normalized
        for value in (channel.get("name"), channel.get("tvg_id"), channel.get("channel_id"))
        if (normalized := _normalize_epg_channel(value))
    }
    if requested & US_XMLTV_UNRELIABLE_CHANNELS:
        return []
    try:
        index = _load_us_epg_index(cache_root)
    except (OSError, ValueError, TypeError, EOFError, ET.ParseError, urllib.error.URLError):
        return []
    matched = _match_epg_channel(channel, index)
    if not matched:
        return []
    now = int(time.time())
    offset = US_XMLTV_TIME_OFFSETS.get(matched, 0)
    programs = [
        {
            **item,
            "start": int(item.get("start", 0)) + offset,
            "stop": int(item.get("stop", 0)) + offset,
        }
        for item in index.get(matched, [])
    ]
    current = next((position for position, item in enumerate(programs)
                    if int(item.get("start", 0)) <= now < int(item.get("stop", 0))), None)
    if current is None:
        current = next((position for position, item in enumerate(programs)
                        if int(item.get("start", 0)) >= now), 0)
    return [dict(item) for item in programs[current:current + 4]]


def online_epg_feed_warning(channel: dict[str, Any]) -> str:
    """Explain why a known-mismatched live feed intentionally has no fallback."""
    requested = {
        normalized
        for value in (channel.get("name"), channel.get("tvg_id"), channel.get("channel_id"))
        if (normalized := _normalize_epg_channel(value))
    }
    if requested & US_XMLTV_UNRELIABLE_CHANNELS:
        return "STREAM AND PUBLIC GUIDE DO NOT MATCH"
    return ""


def fetch_xtream_api(source: dict[str, Any], timeout: float = 30.0) -> list[dict[str, str]]:
    """Load live TV and VOD using the Xtream Codes API."""
    account = _read_json_url(_xtream_endpoint(source, "player_api.php"), timeout)
    info = account.get("user_info", {}) if isinstance(account, dict) else {}
    if str(info.get("auth", "0")) != "1" or str(info.get("status", "")).casefold() != "active":
        return []

    channels: list[dict[str, str]] = []
    for kind, category_action, stream_action, media_path in (
        ("LIVE", "get_live_categories", "get_live_streams", "live"),
        ("VOD", "get_vod_categories", "get_vod_streams", "movie"),
    ):
        categories_data = _read_json_url(
            _xtream_endpoint(source, "player_api.php", action=category_action), timeout
        )
        categories = {
            str(item.get("category_id", "")): _safe_text(item.get("category_name", kind), 100)
            for item in categories_data if isinstance(item, dict)
        } if isinstance(categories_data, list) else {}
        stream_data = _read_json_url(
            _xtream_endpoint(source, "player_api.php", action=stream_action), timeout
        )
        if not isinstance(stream_data, list):
            continue
        for item in stream_data:
            if not isinstance(item, dict) or item.get("stream_id") in (None, ""):
                continue
            category = categories.get(str(item.get("category_id", "")), kind)
            name = _safe_text(item.get("name") or item.get("stream_name") or f"{kind} ITEM", 180)
            extension = str(item.get("container_extension", "")) or ("ts" if media_path == "live" else "mp4")
            channels.append({
                "name": name,
                "url": _xtream_media_url(source, media_path, item.get("stream_id"), extension),
                "group": f"{kind} / {category}",
                "logo": str(item.get("stream_icon", "")),
                "tvg_id": str(item.get("epg_channel_id", "")),
                "stream_id": str(item.get("stream_id", "")),
                "media_type": media_path,
                "source": str(source.get("name", "XTREAM")),
            })
    return channels


def fetch_xtream_vod_info(
    source: dict[str, Any], stream_id: str, timeout: float = 10.0,
) -> dict[str, str]:
    """Return normalized details for one Xtream VOD title.

    Providers commonly omit plot/year/runtime data from the large catalogue
    response.  The 3D store calls this smaller endpoint only when a customer
    opens a case, then caches the result locally.
    """
    payload = _read_json_url(
        _xtream_endpoint(source, "player_api.php", action="get_vod_info", vod_id=stream_id),
        timeout,
    )
    if not isinstance(payload, dict):
        return {}
    info = payload.get("info", {})
    movie = payload.get("movie_data", {})
    if not isinstance(info, dict):
        info = {}
    if not isinstance(movie, dict):
        movie = {}
    release = _safe_text(
        info.get("releasedate") or info.get("release_date") or movie.get("year") or "", 40
    )
    year_match = re.search(r"(?:19|20)\d{2}", release)
    return {
        "synopsis": _safe_text(info.get("plot") or info.get("description") or "", 1600),
        "genre": _safe_text(info.get("genre") or "", 180),
        "year": year_match.group(0) if year_match else "",
        "duration": _safe_text(info.get("duration") or info.get("duration_secs") or "", 80),
        "rating": _safe_text(info.get("rating") or info.get("rating_5based") or "", 24),
        "cover_url": str(info.get("movie_image") or info.get("cover_big") or "").strip(),
    }


_FOREIGN_VOD_NAMES = re.compile(
    r"^(?:AF|BN|BR|DE|ES|FR|IN|IT|LA|MT|NL|PK|PT/BR|SO|TR)\s*-\s*|"
    r"^(?:DANSKE|NORDIC|NORGE|SUOMEN|SVENSKA|VIAPLAY ÍSLANDS|ÍSLANDS)\b",
    re.IGNORECASE,
)


def xtream_group_visible(group: str) -> bool:
    """Keep US, English, and untagged Xtream groups in the default browser.

    Providers remain untouched and the complete response stays in the private
    on-disk cache.  Only explicitly foreign-tagged groups are hidden.  EN is a
    language tag and is intentionally retained.
    """
    normalized = " ".join(str(group or "").split())
    upper = normalized.upper()
    if upper in {"LIVE / FOR ADULTS", "VOD / FOR ADULTS"}:
        return False
    if upper.startswith("LIVE / "):
        category = normalized[7:].strip()
        if "|" not in category:
            return True
        region = category.split("|", 1)[0].strip().upper()
        return region in {"US", "USA", "EN", "4K"}
    if upper.startswith("VOD / "):
        category = normalized[6:].strip()
        if re.match(r"^EN\s*-\s*", category, flags=re.IGNORECASE):
            return True
        if re.match(r"^NETFLIX ASIA\b", category, flags=re.IGNORECASE):
            return False
        return _FOREIGN_VOD_NAMES.search(category) is None
    return True


def filter_xtream_channels(channels: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    return [dict(channel) for channel in channels if xtream_group_visible(str(channel.get("group", "")))]


def _upgrade_cached_xtream_channel(channel: dict[str, Any]) -> dict[str, Any]:
    """Recover stream metadata from credential-bearing URLs in older private caches."""
    upgraded = dict(channel)
    if upgraded.get("stream_id"):
        return upgraded
    parts = [urllib.parse.unquote(part) for part in urllib.parse.urlsplit(str(upgraded.get("url", ""))).path.split("/") if part]
    if len(parts) < 4 or parts[-4] not in {"live", "movie"}:
        return upgraded
    match = re.match(r"^(\d+)(?:\.[A-Za-z0-9]+)?$", parts[-1])
    if not match:
        return upgraded
    upgraded["stream_id"] = match.group(1)
    upgraded["media_type"] = parts[-4]
    return upgraded


def _merge_xtream_channels(
    cached: Iterable[dict[str, Any]], refreshed: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge a partial provider refresh without discarding cached Live or VOD entries."""
    merged: dict[str, dict[str, Any]] = {}
    for channel in (*tuple(cached), *tuple(refreshed)):
        upgraded = _upgrade_cached_xtream_channel(channel)
        key = str(upgraded.get("url", "")).strip()
        if key:
            merged[key] = upgraded
    return list(merged.values())


def public_source_label(source: dict[str, Any]) -> str:
    kind = str(source.get("type", "m3u")).upper()
    name = _safe_text(source.get("name", "TV SOURCE"), 80)
    if kind == "XTREAM":
        try:
            parsed = urllib.parse.urlsplit(xtream_playlist_url(source))
            host = parsed.hostname or "PRIVATE SERVER"
            return f"{name}  •  XTREAM  •  {host}  •  CREDENTIALS SAVED"
        except (TypeError, ValueError):
            return f"{name}  •  XTREAM  •  CONFIGURATION ERROR"
    return f"{name}  •  M3U"


def load_saved_sources(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    values = payload.get("sources", []) if isinstance(payload, dict) else []
    return [dict(item) for item in values if isinstance(item, dict)]


def save_sources(path: Path, sources: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"sources": list(sources)}, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def _source_identity(source: dict[str, Any]) -> str:
    if str(source.get("type", "m3u")).casefold() == "xtream":
        identity = "|".join((
            str(source.get("server", "")).rstrip("/"),
            str(source.get("port", "")),
            str(source.get("username", "")),
        ))
    else:
        identity = str(source.get("url", "")).strip()
    return hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()


def xtream_cache_path(source: dict[str, Any], cache_root: Path) -> Path:
    """Return the private API cache belonging to one configured source."""
    return cache_root / f"{_source_identity(source)}.xtream.json"


def merge_sources(existing: Iterable[dict[str, Any]], additions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in (*tuple(existing), *tuple(additions)):
        if not isinstance(source, dict):
            continue
        kind = str(source.get("type", "m3u")).casefold()
        if kind not in {"m3u", "xtream"}:
            continue
        candidate = dict(source)
        candidate["type"] = kind
        candidate["name"] = _safe_text(candidate.get("name", "TV SOURCE"), 80) or "TV SOURCE"
        try:
            source_url(candidate)
        except (TypeError, ValueError, urllib.parse.PortValueError):
            continue
        merged[_source_identity(candidate)] = candidate
    return list(merged.values())


def import_sources_from_media(removable_root: Path, destination: Path) -> tuple[list[dict[str, Any]], int]:
    """Import PulseArc/TV sources.json and playlist files from removable media."""
    existing = load_saved_sources(destination)
    additions: list[dict[str, Any]] = []
    imported_files = 0
    local_root = destination.parent / "playlists"
    for media_root in removable_root.iterdir() if removable_root.is_dir() else ():
        if not media_root.is_dir():
            continue
        candidate_roots = (media_root / "PulseArc" / "TV", media_root / "pulsearc" / "tv")
        for root in candidate_roots:
            if not root.is_dir():
                continue
            config = root / "sources.json"
            additions.extend(load_saved_sources(config))
            for playlist in (*root.glob("*.m3u"), *root.glob("*.m3u8")):
                if not playlist.is_file() or playlist.stat().st_size > 16 * 1024 * 1024:
                    continue
                local_root.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256(playlist.read_bytes()).hexdigest()[:16]
                target = local_root / f"{digest}{playlist.suffix.casefold()}"
                shutil.copyfile(playlist, target)
                os.chmod(target, 0o600)
                additions.append({"name": playlist.stem, "type": "local", "path": str(target)})
                imported_files += 1
    # Local playlists intentionally bypass merge_sources' HTTP validation.
    local = [item for item in additions if str(item.get("type", "")).casefold() == "local"]
    remote = merge_sources(existing, additions)
    known_paths = {str(item.get("path", "")) for item in existing if item.get("type") == "local"}
    remote.extend(item for item in existing if item.get("type") == "local")
    remote.extend(item for item in local if str(item.get("path", "")) not in known_paths)
    save_sources(destination, remote)
    return remote, len(remote) - len(existing) + imported_files


def fetch_source(source: dict[str, Any], cache_root: Path, timeout: float = 30.0) -> tuple[list[dict[str, str]], bool]:
    """Return channels and whether a cached playlist had to be used."""
    cache_root.mkdir(parents=True, exist_ok=True)
    identity = _source_identity(source) if source.get("type") != "local" else hashlib.sha256(
        str(source.get("path", "")).encode("utf-8")
    ).hexdigest()
    cache_path = cache_root / f"{identity}.m3u"
    api_cache_path = cache_root / f"{identity}.xtream.json"
    data: bytes | None = None
    used_cache = False
    source_type = str(source.get("type", "m3u")).casefold()
    if source_type == "xtream":
        cached_xtream: list[dict[str, Any]] = []
        try:
            cached_channels = json.loads(api_cache_path.read_text(encoding="utf-8"))
            if isinstance(cached_channels, list):
                cached_xtream = [
                    _upgrade_cached_xtream_channel(item)
                    for item in cached_channels if isinstance(item, dict)
                ]
            if cached_xtream and time.time() - api_cache_path.stat().st_mtime < 3600:
                return filter_xtream_channels(cached_xtream), True
        except (OSError, ValueError, TypeError):
            pass
        try:
            channels = fetch_xtream_api(source, timeout)
            if channels:
                channels = _merge_xtream_channels(cached_xtream, channels)
                api_cache_path.write_text(json.dumps(channels, separators=(",", ":")), encoding="utf-8")
                os.chmod(api_cache_path, 0o600)
                return filter_xtream_channels(channels), False
        except (OSError, ValueError, TypeError, json.JSONDecodeError, urllib.error.URLError):
            pass
        if cached_xtream:
            return filter_xtream_channels(cached_xtream), True
    if source_type == "local":
        try:
            data = Path(str(source.get("path", ""))).read_bytes()
        except OSError:
            data = None
    else:
        try:
            request = urllib.request.Request(
                source_url(source),
                headers={"User-Agent": "PulseArc-TV/1.0", "Accept": "audio/x-mpegurl, application/vnd.apple.mpegurl, */*"},
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                length = int(response.headers.get("Content-Length", "0") or 0)
                if length > 64 * 1024 * 1024:
                    raise ValueError("playlist exceeds 64 MB limit")
                data = response.read(64 * 1024 * 1024 + 1)
                if len(data) > 64 * 1024 * 1024:
                    raise ValueError("playlist exceeds 64 MB limit")
            cache_path.write_bytes(data)
            os.chmod(cache_path, 0o600)
        except (OSError, ValueError, urllib.error.URLError):
            try:
                data = cache_path.read_bytes()
                used_cache = True
            except OSError:
                data = None
    if not data:
        return [], used_cache
    text = data.decode("utf-8-sig", errors="replace")
    return parse_m3u(text, str(source.get("name", "PLAYLIST"))), used_cache
