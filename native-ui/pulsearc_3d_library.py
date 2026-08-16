#!/usr/bin/env python3
"""PulseArc walkable 3D plaza and video-store library.

This renderer intentionally uses the legacy fixed-function OpenGL path.  It is
small, has no game-engine dependency, and remains usable on older Intel GPUs.
The scene is an original PulseArc design inspired by late-1990s video-rental
stores: yellow walls, blue/yellow signage, dense face-out cases, glass entry
doors, black carpet, and a fluorescent drop ceiling.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import random
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")

import pygame
from pulsearc_tv import (
    fetch_xtream_vod_info,
    load_saved_sources,
    xtream_cache_path,
    xtream_media_url,
)
from OpenGL.GL import (  # type: ignore[import-not-found]
    GL_BLEND,
    GL_COMPILE,
    GL_COLOR_BUFFER_BIT,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    GL_LINEAR,
    GL_MODELVIEW,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_PROJECTION,
    GL_QUADS,
    GL_RGBA,
    GL_REPEAT,
    GL_SRC_ALPHA,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_TRIANGLES,
    GL_UNSIGNED_BYTE,
    glBegin,
    glBindTexture,
    glCallList,
    glBlendFunc,
    glClear,
    glClearColor,
    glColor4f,
    glDeleteLists,
    glDeleteTextures,
    glDisable,
    glEnable,
    glEnd,
    glEndList,
    glGenLists,
    glGenTextures,
    glLoadIdentity,
    glMatrixMode,
    glNewList,
    glOrtho,
    glPopMatrix,
    glPushMatrix,
    glRotatef,
    glScalef,
    glTexCoord2f,
    glTexImage2D,
    glTexParameteri,
    glTranslatef,
    glVertex3f,
    glViewport,
)
from OpenGL.GLU import gluLookAt, gluPerspective  # type: ignore[import-not-found]


LIBRARY_PATH = Path("/run/pulsearc/library.json")
OPTICAL_ENTRY_PATH = Path("/run/pulsearc/optical-entry.json")
COVERS_PATH = Path.home() / ".cache/pulsearc/covers.json"
SYNOPSES_PATH = Path.home() / ".cache/pulsearc/synopses.json"
TV_CACHE_ROOT = Path.home() / ".cache/pulsearc/tv"
TV_ARTWORK_ROOT = TV_CACHE_ROOT / "artwork"
TV_SOURCES_PATH = Path.home() / ".local/share/pulsearc/tv/sources.json"
VOD_DETAILS_PATH = TV_CACHE_ROOT / "vod-details.json"
VOD_GROUP = "VOD / EN - NEW RELEASE"
SHELF_CAPACITY = 2 * 4 * 12
WALL_SIDE_SLOTS = 60
WALL_BACK_SLOTS = 56
PERIMETER_CAPACITY = (2 * 4 * WALL_SIDE_SLOTS) + (4 * WALL_BACK_SLOTS)
# One six-shelf store page reserves the first centre shelf for every game.
# Dense perimeter racks and the other five double-sided shelves are movies.
VOD_PAGE_SIZE = PERIMETER_CAPACITY + (5 * SHELF_CAPACITY)
INTERNAL_ROOT = Path("/var/lib/pulsearc/library")
REMOVABLE_ROOT = Path("/run/media/gamer")
STORE_STATE_PATH = Path("/run/pulsearc/3d-store-state.json")
ROOM_WIDTH = 22.0
ROOM_HEIGHT = 4.2
PLAZA_MIN_X = -42.0
PLAZA_MAX_X = 42.0
PLAZA_MIN_Y = -40.0

YELLOW = (0.96, 0.76, 0.02, 1.0)
BLUE = (0.04, 0.14, 0.52, 1.0)
DARK_BLUE = (0.018, 0.045, 0.15, 1.0)
BLACK = (0.015, 0.018, 0.024, 1.0)

CAR_MODELS = (
    "compact", "coupe", "hatchback", "minivan", "offroad",
    "pickup", "sedan", "sport", "suv", "wagon",
)

CAR_COLORS = (
    (0.12, 0.38, 0.82, 1.0), (0.78, 0.10, 0.16, 1.0),
    (0.92, 0.62, 0.08, 1.0), (0.10, 0.56, 0.42, 1.0),
    (0.52, 0.18, 0.72, 1.0), (0.72, 0.75, 0.80, 1.0),
    (0.08, 0.10, 0.14, 1.0), (0.90, 0.34, 0.12, 1.0),
)


def _unescape_mount_path(value: str) -> str:
    """Decode the escaping used by /proc/mounts for paths with spaces."""
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def _optical_mount_roots() -> set[Path]:
    """Return mounted ISO/UDF roots so their individual files never become cases."""
    roots: set[Path] = set()
    try:
        lines = Path("/proc/mounts").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return roots
    for line in lines:
        fields = line.split()
        if len(fields) >= 3 and fields[2].casefold() in {"iso9660", "udf"}:
            roots.add(Path(_unescape_mount_path(fields[1])).resolve())
    return roots


def _exclude_optical_disc_files(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep optical media under the dedicated disc detector, not the shelf scanner."""
    roots = _optical_mount_roots()
    if not roots:
        return entries
    visible: list[dict[str, Any]] = []
    for entry in entries:
        source = Path(str(entry.get("source_root", "")))
        path = Path(str(entry.get("path", "")))
        try:
            source = source.resolve()
            path = path.resolve()
        except OSError:
            pass
        if any(source == root or path == root or path.is_relative_to(root) for root in roots):
            continue
        visible.append(entry)
    return visible


def _normalize_ps3_entry(entry: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(entry.get("path", "")))
    parts = tuple(part.casefold() for part in path.parts)
    is_ps3_eboot = (
        path.name.casefold() == "eboot.bin"
        and len(parts) >= 3
        and parts[-2] == "usrdir"
        and parts[-3] == "ps3_game"
    )
    if not (
        str(entry.get("runner", "")).casefold() == "rpcs3"
        or "playstation-3" in parts
        or is_ps3_eboot
    ):
        return entry
    normalized = dict(entry)
    normalized.update(platform="playstation-3", runner="rpcs3", media_kind="disc-image")
    if is_ps3_eboot and str(normalized.get("title", "")).casefold() in {"", "eboot"}:
        normalized["title"] = " ".join(
            path.parents[2].name.replace("_", " ").replace("-", " ").split()
        ).title()
    return normalized


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def vod_content_id(source: str, stream_id: str, url: str = "") -> str:
    identity = f"{source}\0{stream_id or url}".encode("utf-8", errors="replace")
    return f"iptv-vod:{hashlib.sha256(identity).hexdigest()[:24]}"


def vod_artwork_path(url: str, artwork_root: Path = TV_ARTWORK_ROOT) -> Path:
    return artwork_root / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.img"


def is_movie_entry(entry: dict[str, Any]) -> bool:
    platform = str(entry.get("platform") or entry.get("media_kind") or "").casefold()
    media_kind = str(entry.get("media_kind", "")).casefold()
    return platform in {"movie", "video", "dvd-video", "iptv-vod"} or media_kind == "movie"


def load_vod_new_releases(
    cache_root: Path = TV_CACHE_ROOT, artwork_root: Path = TV_ARTWORK_ROOT,
) -> list[dict[str, Any]]:
    """Read the private IPTV caches and expose lightweight 3D-store entries."""
    deduplicated: dict[tuple[str, str], dict[str, Any]] = {}
    sources = [
        source for source in load_saved_sources(TV_SOURCES_PATH)
        if str(source.get("type", "")).casefold() == "xtream"
    ]
    catalogues: list[tuple[Path, dict[str, Any] | None]] = [
        (xtream_cache_path(source, cache_root), source) for source in sources
    ]
    if not catalogues:
        catalogues = [(path, None) for path in sorted(cache_root.glob("*.xtream.json"))]
    for cache_path, configured_source in catalogues:
        values = read_json(cache_path, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict) or str(item.get("group", "")).upper() != VOD_GROUP:
                continue
            source = str((configured_source or {}).get("name") or item.get("source", "XTREAM"))
            stream_id = str(item.get("stream_id", ""))
            url = str(item.get("url", ""))
            if not stream_id and not url:
                continue
            key = (source.casefold(), stream_id or url)
            logo = str(item.get("logo", ""))
            if configured_source is not None and stream_id:
                extension = Path(urllib.parse.urlsplit(url).path).suffix.lstrip(".") or "mp4"
                try:
                    url = xtream_media_url(configured_source, "movie", stream_id, extension)
                except (TypeError, ValueError):
                    pass
            deduplicated[key] = {
                "content_id": vod_content_id(source, stream_id, url),
                "title": str(item.get("name") or "Untitled Movie"),
                "platform": "iptv-vod",
                "media_kind": "movie",
                "group": VOD_GROUP,
                "source": source,
                "stream_id": stream_id,
                "url": url,
                "cover_url": logo,
                "cover_path": str(vod_artwork_path(logo, artwork_root)) if logo else "",
            }
    return sorted(deduplicated.values(), key=lambda entry: str(entry["title"]).casefold())


def _download_cover(entry: dict[str, Any]) -> bool:
    url = str(entry.get("cover_url", ""))
    target = Path(str(entry.get("cover_path", "")))
    if not url or not target or target.is_file():
        return target.is_file()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "PulseArc-3D-Store/1.0"})
        with urllib.request.urlopen(request, timeout=7) as response:
            payload = response.read(6 * 1024 * 1024 + 1)
        if not payload or len(payload) > 6 * 1024 * 1024:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".part")
        temporary.write_bytes(payload)
        temporary.replace(target)
        return True
    except (OSError, ValueError):
        return False


def is_music(entry: dict[str, Any]) -> bool:
    platform = str(entry.get("platform") or entry.get("media_kind") or "").lower()
    return platform in {"music", "audio"} or Path(str(entry.get("path", ""))).suffix.lower() in {
        ".mp3", ".wav", ".flac", ".ogg", ".m4a",
    }


def is_internal(entry: dict[str, Any]) -> bool:
    if is_music(entry):
        return False
    path = Path(str(entry.get("path", "")))
    root = Path(str(entry.get("source_root", "")))
    try:
        return path.is_relative_to(INTERNAL_ROOT) or root.is_relative_to(INTERNAL_ROOT)
    except ValueError:
        return False


def is_new_release(entry: dict[str, Any]) -> bool:
    """Return true for playable games currently present on removable media."""
    if is_music(entry):
        return False
    platform = str(entry.get("platform") or entry.get("media_kind") or "").lower()
    if platform in {"movie", "video", "dvd-video", "music", "audio"}:
        return False
    try:
        path = Path(str(entry.get("path", ""))).resolve()
        root = Path(str(entry.get("source_root", ""))).resolve()
        removable = REMOVABLE_ROOT.resolve()
        return path.is_relative_to(removable) and root.is_relative_to(removable)
    except (OSError, ValueError):
        return False


def angle_delta(value: float) -> float:
    return (value + math.pi) % (math.tau) - math.pi


class Store:
    def __init__(self, selection_file: Path, self_test: bool = False) -> None:
        pygame.init()
        pygame.joystick.init()
        flags = pygame.OPENGL | pygame.DOUBLEBUF
        if not self_test:
            flags |= pygame.FULLSCREEN
        if self_test:
            size = (960, 540)
        else:
            desktop_width, desktop_height = pygame.display.get_desktop_sizes()[0]
            render_scale = min(1.0, 1920 / max(1, desktop_width), 1080 / max(1, desktop_height))
            size = (max(640, int(desktop_width * render_scale)), max(360, int(desktop_height * render_scale)))
        self.screen = pygame.display.set_mode(size, flags, vsync=1)
        self.width, self.height = self.screen.get_size()
        glViewport(0, 0, self.width, self.height)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(67.0, self.width / max(1, self.height), 0.07, 80.0)
        glMatrixMode(GL_MODELVIEW)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glClearColor(0.20, 0.48, 0.76, 1.0)
        self.textures: dict[str, int] = {}

        self.selection_file = selection_file
        self.self_test = self_test
        library_values = _exclude_optical_disc_files(
            [_normalize_ps3_entry(entry) for entry in read_json(LIBRARY_PATH, []) if isinstance(entry, dict)]
        )
        optical_entry = read_json(OPTICAL_ENTRY_PATH, {})
        if isinstance(optical_entry, dict) and optical_entry.get("content_id"):
            optical_id = str(optical_entry.get("content_id", ""))
            library_values = [
                entry for entry in library_values
                if str(entry.get("content_id", "")) != optical_id
            ]
            library_values.insert(0, optical_entry)
        new_releases = [entry for entry in library_values if is_new_release(entry)]
        installed = [entry for entry in library_values if is_internal(entry)]
        self.external_entries = new_releases
        self.installed_entries = installed
        self.vod_catalog = load_vod_new_releases()
        if self_test:
            # Exercise the same VOD rendering path without allocating an entire
            # commercial catalogue during the bounded deployment smoke test.
            self.vod_catalog = self.vod_catalog[:12]
        self.vod_page = 0
        persistent_movie_count = sum(1 for entry in (*new_releases, *installed) if is_movie_entry(entry))
        self.vod_page_size = max(1, VOD_PAGE_SIZE - min(VOD_PAGE_SIZE - 1, persistent_movie_count))
        self.vod_page_count = max(1, math.ceil(len(self.vod_catalog) / self.vod_page_size))
        vod_entries = self.vod_catalog[:self.vod_page_size]
        # External titles are deliberately first so NEW RELEASES occupies the
        # first rack on the left when entering the store.
        self.entries = [*vod_entries, *new_releases, *installed]
        self.vod_ids = {str(entry.get("content_id", "")) for entry in self.vod_catalog}
        self.new_release_ids = {str(entry.get("content_id", "")) for entry in new_releases}
        self.covers = read_json(COVERS_PATH, {})
        synopsis_values = read_json(SYNOPSES_PATH, {})
        self.synopses = synopsis_values if isinstance(synopsis_values, dict) else {}
        detail_values = read_json(VOD_DETAILS_PATH, {})
        self.vod_details = detail_values if isinstance(detail_values, dict) else {}
        if not self_test:
            self._draw_loading_screen("LOADING NEW RELEASE SHELVES")
            self._prefetch_vod_covers(vod_entries)
        self.model_meshes: dict[str, list[tuple[float, float, float, float, float, str]]] = {}
        self.model_materials: dict[str, dict[str, tuple[float, float, float, float]]] = {}
        self.model_lists: dict[str, int] = {}
        # Every model in the bundled CC0 pack is available.  A new shuffled
        # selection is used on every Plaza visit so the parking lot feels
        # occupied without drawing twenty vehicles at once on older GPUs.
        self.parked_models = random.choices(CAR_MODELS, k=12)
        self.parked_colors = [random.choice(CAR_COLORS) for _model in self.parked_models]
        people_models = (
            "Casual_Female", "Casual_Male", "Casual2_Female", "Casual2_Male",
            "Casual3_Female", "Casual3_Male", "Worker_Female", "Worker_Male",
        )
        people_colors = (
            (0.20, 0.57, 0.94, 1.0), (0.92, 0.34, 0.48, 1.0),
            (0.23, 0.72, 0.46, 1.0), (0.94, 0.66, 0.20, 1.0),
            (0.54, 0.35, 0.88, 1.0), (0.10, 0.68, 0.75, 1.0),
        )
        routes = (
            ((-5.0, -3.0), (27.0, -3.0)),
            ((-13.5, -5.0), (-13.5, -29.0)),
            ((35.5, -5.0), (35.5, -29.0)),
            ((-5.0, -35.0), (28.0, -35.0)),
            ((-5.5, -8.0), (27.0, -8.0)),
            ((-7.0, -30.5), (29.0, -30.5)),
        )
        local_actor_root = Path(__file__).resolve().parent / "assets/models/pulsearc-local"
        private_people = ("angela", "guinevere", "rafaela")
        private_people_ready = all((local_actor_root / f"{name}.obj").is_file() for name in private_people)
        self.plaza_people = []
        for index, route in enumerate(routes):
            if private_people_ready:
                name = private_people[index % len(private_people)]
                actor = {
                    "group": "pulsearc-local", "model": name, "texture": f"{name}.png",
                    "color": None, "scale": 0.94,
                }
            else:
                actor = {
                    "group": "quaternius-people", "model": random.choice(people_models),
                    "texture": None, "color": random.choice(people_colors), "scale": 0.82,
                }
            self.plaza_people.append({
                **actor,
                "route": route,
                "phase": random.random() * 2.0,
                "speed": random.uniform(0.055, 0.095),
            })
        private_wolf_ready = (local_actor_root / "wolf.obj").is_file()
        pet_routes = (
            ((-3.0, -5.4), (24.0, -5.4)),
            ((-11.0, -8.0), (-11.0, -27.0)),
            ((33.0, -8.0), (33.0, -27.0)),
        )
        fallback_pets = random.sample(("animal-dog", "animal-cat", "animal-bunny", "animal-fox"), k=3)
        self.plaza_pets = []
        for index, route in enumerate(pet_routes):
            pet = (
                {"group": "pulsearc-local", "model": "wolf", "texture": "wolf.png", "scale": 0.78}
                if private_wolf_ready else
                {"group": "kenney-pets", "model": fallback_pets[index], "texture": None, "scale": 0.62}
            )
            self.plaza_pets.append({
                **pet,
                "route": route,
                "phase": random.random() * 2.0,
                "speed": random.uniform(0.075, 0.12),
            })
        self._configure_shelf_layout()
        self.case_positions = self._case_positions()
        # Enter from the Plaza approach, facing the Video Library doors.
        # Restoring the old camera position could strand players behind a
        # shelf after the modular layout changed, so Plaza entry is stable.
        saved_state: dict[str, Any] = {}
        self.player = [11.0, -2.35]
        self.angle = math.pi / 2
        if isinstance(saved_state, dict):
            try:
                candidate = [float(saved_state.get("x", 11.0)), float(saved_state.get("y", 2.3))]
                in_store = 0.55 < candidate[0] < ROOM_WIDTH - 0.55 and -0.7 < candidate[1] < self.room_depth - 0.55
                in_plaza = PLAZA_MIN_X + 0.8 < candidate[0] < PLAZA_MAX_X - 0.8 and PLAZA_MIN_Y + 0.8 < candidate[1] <= 0.0
                if in_store or in_plaza:
                    self.player = candidate
                self.angle = float(saved_state.get("angle", math.pi / 2)) % math.tau
            except (TypeError, ValueError):
                pass
        # Keep enough raw axes for both SDL's standard Xbox mapping and the
        # xpad layout where the triggers precede the right stick.
        self.axes = {axis: 0.0 for axis in range(8)}
        self.turn_axis = 2
        self.pitch_axis = 3
        self.pitch = 0.0
        self.focus: int | None = None
        self.detail_index: int | None = None
        self.running = True
        self.clock = pygame.time.Clock()
        self.controllers: dict[int, pygame.joystick.Joystick] = {}
        self.last_hat = (0, 0)
        self._preload_scene_textures()
        self.static_scene = int(glGenLists(1))
        glNewList(self.static_scene, GL_COMPILE)
        self._room()
        self._shelves()
        self._front_desks()
        self._plaza()
        glEndList()
        # Covers do not move during a Plaza visit. Cache the normal cases in
        # one GPU display list and redraw only the focused case each frame.
        self.case_scene = int(glGenLists(1))
        glNewList(self.case_scene, GL_COMPILE)
        self._base_cases()
        glEndList()
        self.crosshair_scene = int(glGenLists(1))
        glNewList(self.crosshair_scene, GL_COMPILE)
        glBegin(GL_QUADS)
        for x1, x2, y1, y2 in (
            (-13, -4, -1, 1), (4, 13, -1, 1),
            (-1, 1, -13, -4), (-1, 1, 4, 13),
            (-2, 2, -2, 2),
        ):
            glVertex3f(x1, y1, 0)
            glVertex3f(x2, y1, 0)
            glVertex3f(x2, y2, 0)
            glVertex3f(x1, y2, 0)
        glEnd()
        glEndList()
        self._start_lounge_music()
        for index in range(pygame.joystick.get_count()):
            stick = pygame.joystick.Joystick(index)
            stick.init()
            self.controllers[stick.get_instance_id()] = stick
            self._configure_turn_axis(stick)

    def _configure_turn_axis(self, stick: pygame.joystick.Joystick) -> None:
        """Account for the two common raw-axis layouts used by Xbox pads.

        SDL exposes the right-stick X axis as axis 2 on its modern mapping,
        while several xpad/Xbox 360-compatible devices expose it as axis 3
        with a trigger occupying axis 2.
        """
        name = stick.get_name().lower()
        if "xbox" in name or "x-box" in name or "xinput" in name:
            self.turn_axis = 3
            self.pitch_axis = 4
        else:
            self.turn_axis = 2
            self.pitch_axis = 3
        print(
            f"PULSEARC_3D_INPUT controller={stick.get_name()!r} "
            f"axes={stick.get_numaxes()} turn_axis={self.turn_axis} "
            f"pitch_axis={self.pitch_axis}",
            flush=True,
        )

    def _prefetch_vod_covers(self, entries: list[dict[str, Any]]) -> None:
        """Lazy-load only the shelf page being opened, never the full provider."""
        pending = [entry for entry in entries if entry.get("cover_url") and not Path(str(entry.get("cover_path", ""))).is_file()]
        if not pending:
            return
        # Concurrent network I/O keeps a newly opened shelf page responsive;
        # the resulting files are reused on every later visit.
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
            list(executor.map(_download_cover, pending))

    def _draw_loading_screen(self, message: str) -> None:
        """Present a branded frame before network/cache work can block startup."""
        surface = pygame.Surface((960, 540), pygame.SRCALPHA)
        surface.fill((5, 12, 38, 255))
        for row in range(0, 540, 54):
            shade = 22 + (row // 54) * 3
            pygame.draw.rect(surface, (9, shade, 74, 255), (0, row, 960, 27))
        pygame.draw.rect(surface, (255, 214, 37, 255), (76, 91, 808, 126), border_radius=18)
        pygame.draw.rect(surface, (20, 55, 170, 255), (87, 102, 786, 104), border_radius=13)
        brand_font = pygame.font.SysFont("DejaVu Sans", 64, bold=True, italic=True)
        status_font = pygame.font.SysFont("DejaVu Sans", 29, bold=True)
        hint_font = pygame.font.SysFont("DejaVu Sans", 20)
        brand = brand_font.render("GAMEBUSTER", True, (255, 224, 48))
        status = status_font.render(message, True, (242, 248, 255))
        hint = hint_font.render("Preparing this shelf page and its locally cached covers...", True, (132, 218, 255))
        surface.blit(brand, brand.get_rect(center=(480, 154)))
        surface.blit(status, status.get_rect(center=(480, 315)))
        surface.blit(hint, hint.get_rect(center=(480, 369)))
        texture = self._texture_from_surface("loading:gamebuster", surface, surface.get_size())
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glDisable(GL_DEPTH_TEST)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, self.width, 0, self.height, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        self._textured_quad(texture, ((0, 0, 0), (self.width, 0, 0),
                                      (self.width, self.height, 0), (0, self.height, 0)))
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glEnable(GL_DEPTH_TEST)
        pygame.display.flip()

    @staticmethod
    def _friendly_label(entry: dict[str, Any], new_release_ids: set[str]) -> str:
        friendly = {
            "windows": "PC GAMES", "linux": "LINUX GAMES", "playstation": "PLAYSTATION",
            "playstation-2": "PLAYSTATION 2", "playstation-3": "PLAYSTATION 3",
            "nintendo-64": "NINTENDO 64", "super-nintendo": "SUPER NINTENDO",
            "mega-drive": "SEGA GENESIS", "nes": "NINTENDO", "gamecube": "GAMECUBE",
            "wii": "NINTENDO WII", "wii-u": "NINTENDO WII U", "psp": "PSP",
            "dreamcast": "DREAMCAST", "movie": "MOVIES", "video": "MOVIES",
            "dvd-video": "MOVIES", "iptv-vod": "VOD NEW RELEASES",
        }
        platform = str(entry.get("platform") or entry.get("media_kind") or "OTHER").lower()
        content_id = str(entry.get("content_id", ""))
        return "NEW RELEASES" if content_id in new_release_ids else friendly.get(
            platform, platform.replace("-", " ").upper()
        )

    def _configure_shelf_layout(self) -> None:
        capacity = SHELF_CAPACITY
        perimeter_capacity = PERIMETER_CAPACITY
        vod_indices: list[int] = []
        local_movie_indices: list[int] = []
        game_indices: list[int] = []
        for index, entry in enumerate(self.entries):
            platform = str(entry.get("platform") or entry.get("media_kind") or "").casefold()
            content_id = str(entry.get("content_id", ""))
            if content_id in self.vod_ids or platform == "iptv-vod":
                vod_indices.append(index)
            elif is_movie_entry(entry):
                local_movie_indices.append(index)
            else:
                game_indices.append(index)

        # Local movies lead into the provider catalogue, while all games share
        # one predictable rack near the entrance instead of being scattered by
        # system. The current public library is well within this shelf's 96 slots.
        movie_indices = [*local_movie_indices, *vod_indices]
        self.perimeter_assignment = (
            "MOVIES", movie_indices[:perimeter_capacity]
        ) if movie_indices else ("", [])
        self.island_assignments = [("ALL GAMES", game_indices[:capacity])] if game_indices else []
        for offset in range(perimeter_capacity, len(movie_indices), capacity):
            self.island_assignments.append(("MOVIES", movie_indices[offset:offset + capacity]))
        # A very large game collection cannot silently disappear. Overflow is
        # exceptional, but remains accessible on an adjacent game rack.
        for offset in range(capacity, len(game_indices), capacity):
            self.island_assignments.append(("ALL GAMES", game_indices[offset:offset + capacity]))
        self.shelf_assignments = [self.perimeter_assignment, *self.island_assignments]
        aisle_rows = max(3, math.ceil(max(1, len(self.island_assignments)) / 2))
        self.island_shelves = tuple(
            shelf for row in range(aisle_rows) for shelf in (
                (2.2, 9.2, 8.0 + row * 6.0),
                (12.8, 19.8, 8.0 + row * 6.0),
            )
        )
        self.room_depth = 9.0 + aisle_rows * 6.0
        self.system_labels = [label for label, _indices in self.island_assignments[:len(self.island_shelves)]]

    def _change_vod_page(self, delta: int) -> None:
        if not self.vod_catalog or self.vod_page_count <= 1:
            return
        old_page = self.vod_catalog[
            self.vod_page * self.vod_page_size:(self.vod_page + 1) * self.vod_page_size
        ]
        self.vod_page = (self.vod_page + delta) % self.vod_page_count
        vod_entries = self.vod_catalog[
            self.vod_page * self.vod_page_size:(self.vod_page + 1) * self.vod_page_size
        ]
        self.entries = [*vod_entries, *self.external_entries, *self.installed_entries]
        # Discard only old VOD GPU textures. The provider files remain cached.
        for entry in old_page:
            for key in (str(entry.get("cover_path", "")), f"detail:{entry.get('content_id', '')}"):
                texture = self.textures.pop(key, None)
                if texture:
                    glDeleteTextures([texture])
        self._draw_loading_screen(
            f"LOADING NEW RELEASE SHELVES  {self.vod_page + 1}/{self.vod_page_count}"
        )
        self._prefetch_vod_covers(vod_entries)
        self._configure_shelf_layout()
        self.case_positions = self._case_positions()
        self.focus = None
        self.detail_index = None
        glDeleteLists(self.static_scene, 1)
        glDeleteLists(self.case_scene, 1)
        self._preload_scene_textures()
        self.static_scene = int(glGenLists(1))
        glNewList(self.static_scene, GL_COMPILE)
        self._room(); self._shelves(); self._front_desks(); self._plaza()
        glEndList()
        self.case_scene = int(glGenLists(1))
        glNewList(self.case_scene, GL_COMPILE)
        self._base_cases()
        glEndList()

    def _case_positions(self) -> list[tuple[float, float, float, int]]:
        positions: list[tuple[float, float, float, int]] = []
        if not self.entries:
            return positions
        slots_per_face = 12
        levels = (0.14, 0.72, 1.30, 1.88)
        perimeter_indices = self.perimeter_assignment[1] if hasattr(self, "perimeter_assignment") else []
        perimeter_slots: list[tuple[float, float, float]] = []
        wall_start, wall_end = 5.35, self.room_depth - 1.25
        side_y = [
            wall_start + slot * ((wall_end - wall_start) / max(1, WALL_SIDE_SLOTS - 1))
            for slot in range(WALL_SIDE_SLOTS)
        ]
        for wall_x in (0.76, ROOM_WIDTH - 0.76):
            for z in levels:
                for y in side_y:
                    perimeter_slots.append((wall_x, y, z))
        back_y = self.room_depth - 0.76
        for z in levels:
            for slot in range(WALL_BACK_SLOTS):
                x = 1.45 + slot * ((ROOM_WIDTH - 2.90) / max(1, WALL_BACK_SLOTS - 1))
                perimeter_slots.append((x, back_y, z))
        for index, (x, y, z) in zip(perimeter_indices, perimeter_slots):
            positions.append((x, y, z, index))

        for shelf_index, (x1, x2, shelf_y) in enumerate(self.island_shelves):
            if shelf_index >= len(self.island_assignments):
                break
            _label, assigned_indices = self.island_assignments[shelf_index]
            # Covers sit just outside the shelf lip so they remain fully visible.
            available: list[tuple[float, float, float]] = []
            for face_y in (shelf_y - 0.535, shelf_y + 0.535):
                for z in levels:
                    for slot in range(slots_per_face):
                        x = x1 + 0.44 + slot * ((x2 - x1 - 0.88) / max(1, slots_per_face - 1))
                        available.append((x, face_y, z))
            for index, (x, face_y, z) in zip(assigned_indices, available):
                positions.append((x, face_y, z, index))
        return positions

    def _preload_scene_textures(self) -> None:
        """Create textures before compiling the static display list."""
        for material in (
            "carpet", "ceiling", "wall", "wall-blue", "rug", "shelf",
            "plaza-asphalt", "plaza-sky", "plaza-sky-top", "car-colormap", "pet-colormap",
        ):
            self._material_texture(material)
        for label in (
            *self.system_labels,
            "AVAILABLE TITLES",
            "PULSEARC VIDEO & GAMES",
            "PLEASE BE KIND • REWIND",
            "GAMEBUSTER",
            "MOVIE THEATER",
            "INTERNET CAFE",
            "PULSEARC NET CAFE",
            "PULSE ARCADE",
        ):
            self._text_texture(label)
        for _label, indices in self.island_assignments:
            if indices:
                self._cover_texture(self.entries[indices[0]])
                self._cover_texture(self.entries[indices[-1]])

    @staticmethod
    def _color(color: tuple[float, float, float, float], factor: float = 1.0) -> None:
        glColor4f(color[0] * factor, color[1] * factor, color[2] * factor, color[3])

    def _box(self, x1: float, x2: float, y1: float, y2: float, z1: float, z2: float,
             color: tuple[float, float, float, float]) -> None:
        glDisable(GL_TEXTURE_2D)
        glBegin(GL_QUADS)
        self._color(color, 1.0)
        for vertex in ((x1, y1, z2), (x2, y1, z2), (x2, y2, z2), (x1, y2, z2)):
            glVertex3f(*vertex)
        self._color(color, 0.78)
        for vertex in ((x1, y1, z1), (x1, y2, z1), (x2, y2, z1), (x2, y1, z1)):
            glVertex3f(*vertex)
        self._color(color, 0.9)
        for vertex in ((x1, y1, z1), (x2, y1, z1), (x2, y1, z2), (x1, y1, z2)):
            glVertex3f(*vertex)
        self._color(color, 0.66)
        for vertex in ((x2, y2, z1), (x1, y2, z1), (x1, y2, z2), (x2, y2, z2)):
            glVertex3f(*vertex)
        self._color(color, 0.82)
        for vertex in ((x1, y2, z1), (x1, y1, z1), (x1, y1, z2), (x1, y2, z2)):
            glVertex3f(*vertex)
        self._color(color, 0.72)
        for vertex in ((x2, y1, z1), (x2, y2, z1), (x2, y2, z2), (x2, y1, z2)):
            glVertex3f(*vertex)
        glEnd()

    def _texture_from_surface(
        self,
        key: str,
        surface: pygame.Surface,
        size: tuple[int, int] = (256, 384),
    ) -> int:
        if key in self.textures:
            return self.textures[key]
        width, height = size
        surface = pygame.transform.smoothscale(surface.convert_alpha(), size)
        payload = pygame.image.tostring(surface, "RGBA", True)
        texture = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D, texture)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, payload)
        self.textures[key] = texture
        return texture

    def _cover_texture(self, entry: dict[str, Any]) -> int | None:
        content_id = str(entry.get("content_id", ""))
        path = str(self.covers.get(content_id, "") or entry.get("cover_path", ""))
        if path and Path(path).is_file():
            try:
                return self._texture_from_surface(path, pygame.image.load(path), (192, 288))
            except (OSError, pygame.error):
                pass
        # Attractive local fallback, still readable as a case from a distance.
        surface = pygame.Surface((256, 384), pygame.SRCALPHA)
        hue = abs(hash(content_id))
        surface.fill((42 + hue % 90, 28 + (hue // 7) % 85, 80 + (hue // 13) % 130))
        pygame.draw.rect(surface, (250, 210, 45), surface.get_rect(), 9)
        font = pygame.font.SysFont("DejaVu Sans", 33, bold=True)
        words = str(entry.get("title", "Unknown")).upper().split()
        for line, word in enumerate(words[:5]):
            glyph = font.render(word[:14], True, (245, 247, 255))
            surface.blit(glyph, glyph.get_rect(center=(128, 105 + line * 48)))
        return self._texture_from_surface(f"fallback:{content_id}", surface, (192, 288))

    def _ensure_vod_details(self, index: int) -> None:
        if not (0 <= index < len(self.entries)):
            return
        entry = self.entries[index]
        content_id = str(entry.get("content_id", ""))
        if content_id not in self.vod_ids:
            return
        cached = self.vod_details.get(content_id, {})
        if isinstance(cached, dict) and cached.get("synopsis"):
            entry.update(cached)
            return
        source_name = str(entry.get("source", ""))
        source = next(
            (item for item in load_saved_sources(TV_SOURCES_PATH)
             if str(item.get("name", "")).casefold() == source_name.casefold()),
            None,
        )
        if source is None:
            return
        try:
            details = fetch_xtream_vod_info(source, str(entry.get("stream_id", "")), timeout=8.0)
        except (OSError, TypeError, ValueError):
            return
        if not details:
            return
        entry.update({key: value for key, value in details.items() if value})
        self.vod_details[content_id] = {key: value for key, value in details.items() if value}
        try:
            VOD_DETAILS_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = VOD_DETAILS_PATH.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(self.vod_details, ensure_ascii=False), encoding="utf-8")
            temporary.replace(VOD_DETAILS_PATH)
        except OSError:
            pass

    def _detail_texture(self, entry: dict[str, Any]) -> int:
        """Create one cached synopsis card inside the active 3D renderer."""
        content_id = str(entry.get("content_id", ""))
        key = f"detail:{content_id}"
        if key in self.textures:
            return self.textures[key]

        surface = pygame.Surface((1280, 720), pygame.SRCALPHA)
        surface.fill((3, 7, 18, 238))
        pygame.draw.rect(surface, (13, 23, 54, 246), (34, 34, 1212, 652), border_radius=28)
        pygame.draw.rect(surface, (255, 218, 45, 255), (34, 34, 1212, 652), 5, border_radius=28)
        pygame.draw.rect(surface, (35, 72, 188, 255), (55, 55, 350, 610), border_radius=18)

        cover_path = str(self.covers.get(content_id, "") or entry.get("cover_path", ""))
        cover: pygame.Surface | None = None
        if cover_path and Path(cover_path).is_file():
            try:
                cover = pygame.image.load(cover_path).convert_alpha()
            except (OSError, pygame.error):
                pass
        if cover is None:
            cover = pygame.Surface((300, 440), pygame.SRCALPHA)
            cover.fill((25, 40, 92, 255))
            pygame.draw.rect(cover, (255, 218, 45), cover.get_rect(), 7)
        surface.blit(pygame.transform.smoothscale(cover, (300, 440)), (80, 78))

        title_font = pygame.font.SysFont("DejaVu Sans", 48, bold=True)
        heading_font = pygame.font.SysFont("DejaVu Sans", 23, bold=True)
        body_font = pygame.font.SysFont("DejaVu Sans", 25)
        control_font = pygame.font.SysFont("DejaVu Sans", 20, bold=True)
        title = str(entry.get("title") or "Unknown Title")
        platform = str(entry.get("platform") or entry.get("media_kind") or "Other").replace("-", " ").upper()
        synopsis = str(entry.get("synopsis") or self.synopses.get(content_id, "")).strip()
        if title.casefold() == "hell on rails":
            synopsis = ""
        if not synopsis and title.casefold() != "hell on rails":
            synopsis = f"{title} is installed and ready to play. A full synopsis has not been downloaded yet."

        surface.blit(title_font.render(title[:34], True, (244, 248, 255)), (440, 72))
        surface.blit(heading_font.render(platform, True, (255, 218, 45)), (443, 137))
        surface.blit(heading_font.render("SYNOPSIS", True, (91, 226, 255)), (443, 201))
        lines: list[str] = []
        line = ""
        for word in synopsis[:700].split():
            candidate = f"{line} {word}".strip()
            if body_font.size(candidate)[0] <= 735:
                line = candidate
            else:
                if line:
                    lines.append(line)
                line = word
            if len(lines) >= 10:
                break
        if line and len(lines) < 10:
            lines.append(line)
        for row, text in enumerate(lines):
            surface.blit(body_font.render(text, True, (225, 234, 252)), (443, 245 + row * 34))

        pygame.draw.rect(surface, (8, 14, 34, 245), (440, 600, 752, 52), border_radius=12)
        controls = "A  PLAY    X  INSTALL INTERNALLY    B  BACK" if is_new_release(entry) else "A  PLAY        B  BACK TO STORE"
        surface.blit(control_font.render(controls, True, (255, 218, 45)), (475, 614))
        return self._texture_from_surface(key, surface, (1280, 720))

    def _draw_detail_overlay(self) -> None:
        if self.detail_index is None or not (0 <= self.detail_index < len(self.entries)):
            return
        texture = self._detail_texture(self.entries[self.detail_index])
        glDisable(GL_DEPTH_TEST)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, self.width, 0, self.height, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        self._textured_quad(texture, ((0, 0, 0), (self.width, 0, 0),
                                      (self.width, self.height, 0), (0, self.height, 0)))
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glEnable(GL_DEPTH_TEST)

    def _text_texture(self, text: str, foreground=(255, 242, 90), background=(18, 41, 130)) -> int:
        key = f"text:{text}:{foreground}:{background}"
        if key in self.textures:
            return self.textures[key]
        font = pygame.font.SysFont("DejaVu Sans", 48, bold=True, italic=True)
        glyph = font.render(text, True, foreground)
        surface = pygame.Surface((max(256, glyph.get_width() + 50), 96), pygame.SRCALPHA)
        surface.fill((*background, 255))
        pygame.draw.rect(surface, (255, 219, 45), surface.get_rect(), 6)
        surface.blit(glyph, glyph.get_rect(center=surface.get_rect().center))
        return self._texture_from_surface(key, surface, (512, 128))

    def _material_texture(self, material: str) -> int:
        key = f"material:{material}"
        if key in self.textures:
            return self.textures[key]

        asset_names = {
            "carpet": "carpet-dark.webp",
            "ceiling": "ceiling-white.webp",
            "wall": "wall-yellow-plaster.webp",
            "wall-blue": "wall-blue-brick.webp",
            "plaza-asphalt": "plaza-asphalt.png",
            "plaza-sky": "plaza-sky-mountains.png",
            "plaza-sky-top": "plaza-sky-clouds.png",
            "car-colormap": "models/kenney-car-kit/colormap.png",
            "pet-colormap": "models/kenney-pets/colormap.png",
        }
        asset_name = asset_names.get(material)
        if asset_name:
            asset_path = Path(__file__).resolve().parent / "assets" / asset_name
            if asset_path.is_file():
                try:
                    loaded = pygame.image.load(asset_path)
                    return self._texture_from_surface(key, loaded, loaded.get_size())
                except (OSError, pygame.error):
                    pass

        if material == "carpet":
            size = (1024, 1024)
            surface = pygame.Surface(size, pygame.SRCALPHA)
            surface.fill((12, 15, 24, 255))
            # Dense charcoal rental-store carpet with restrained blue flecks.
            for y in range(0, 1024, 8):
                shade = 18 + ((y * 13) % 11)
                pygame.draw.line(surface, (shade, shade + 2, shade + 8, 255), (0, y), (1024, y), 2)
            for index in range(620):
                x = (index * 193) % 1024
                y = (index * 431) % 1024
                color = (20, 47, 78, 170) if index % 3 else (56, 25, 76, 150)
                pygame.draw.line(surface, color, (x, y), (x + 3, y + 1), 1)
        elif material == "ceiling":
            size = (1024, 1024)
            surface = pygame.Surface(size, pygame.SRCALPHA)
            surface.fill((205, 201, 184, 255))
            for x in range(0, 1024, 128):
                pygame.draw.line(surface, (132, 130, 121, 255), (x, 0), (x, 1024), 3)
                pygame.draw.line(surface, (235, 232, 217, 180), (x + 4, 0), (x + 4, 1024), 1)
            for y in range(0, 1024, 128):
                pygame.draw.line(surface, (132, 130, 121, 255), (0, y), (1024, y), 3)
                pygame.draw.line(surface, (235, 232, 217, 180), (0, y + 4), (1024, y + 4), 1)
            for index in range(320):
                x = (index * 97) % 1024
                y = (index * 211) % 1024
                pygame.draw.circle(surface, (162, 159, 148, 105), (x, y), 1)
        elif material == "wall":
            size = (512, 512)
            surface = pygame.Surface(size, pygame.SRCALPHA)
            for y in range(512):
                factor = y / 511
                color = (246, 194 - int(18 * factor), 20 - int(7 * factor), 255)
                pygame.draw.line(surface, color, (0, y), (511, y))
            for index in range(160):
                x = (index * 83) % 512
                y = (index * 149) % 430
                pygame.draw.circle(surface, (255, 226, 75, 38), (x, y), 2)
            pygame.draw.rect(surface, (19, 37, 105, 255), (0, 444, 512, 24))
            pygame.draw.rect(surface, (246, 220, 50, 255), (0, 444, 512, 4))
            pygame.draw.rect(surface, (27, 25, 30, 255), (0, 468, 512, 44))
        elif material == "wall-blue":
            size = (512, 512)
            surface = pygame.Surface(size, pygame.SRCALPHA)
            surface.fill((34, 55, 128, 255))
            for y in range(0, 512, 64):
                pygame.draw.line(surface, (75, 99, 176, 255), (0, y), (512, y), 4)
                offset = 0 if (y // 64) % 2 == 0 else 64
                for x in range(offset, 512, 128):
                    pygame.draw.line(surface, (75, 99, 176, 255), (x, y), (x, min(512, y + 64)), 4)
        elif material == "glass":
            size = (1024, 512)
            surface = pygame.Surface(size, pygame.SRCALPHA)
            for y in range(512):
                factor = y / 511
                color = (
                    90 + int(26 * factor),
                    132 + int(28 * factor),
                    166 + int(30 * factor),
                    34,
                )
                pygame.draw.line(surface, color, (0, y), (1023, y))
            # Strong, sparse diagonal glare makes the collision boundary clear
            # while leaving the shop interior visible through the glass.
            for offset in (-110, 245, 600, 955):
                pygame.draw.line(surface, (238, 250, 255, 145),
                                 (offset, 0), (offset + 210, 430), 28)
                pygame.draw.line(surface, (160, 224, 255, 80),
                                 (offset + 48, 0), (offset + 258, 430), 8)
            pygame.draw.line(surface, (220, 244, 255, 95), (0, 34), (1024, 34), 5)
        elif material == "rug":
            size = (1024, 512)
            surface = pygame.Surface(size, pygame.SRCALPHA)
            for y in range(512):
                factor = y / 511
                pygame.draw.line(
                    surface,
                    (10 + int(15 * factor), 18, 52 + int(38 * factor), 255),
                    (0, y),
                    (1023, y),
                )
            pygame.draw.rect(surface, (14, 219, 246, 255), surface.get_rect(), 18, border_radius=38)
            pygame.draw.rect(surface, (244, 38, 193, 255), surface.get_rect().inflate(-34, -34), 9, border_radius=30)
            # Fine neon grid fibers make the mat feel woven rather than flat.
            for x in range(45, 1024, 54):
                pygame.draw.line(surface, (47, 104, 185, 85), (x, 42), (x, 470), 2)
            for y in range(48, 512, 42):
                pygame.draw.line(surface, (154, 47, 185, 70), (42, y), (982, y), 2)
            title_font = pygame.font.SysFont("DejaVu Sans", 94, bold=True, italic=True)
            subtitle_font = pygame.font.SysFont("DejaVu Sans", 35, bold=True)
            title = title_font.render("PULSEARC", True, (250, 243, 92))
            subtitle = subtitle_font.render("GAMES  •  MOVIES  •  MUSIC", True, (225, 238, 255))
            surface.blit(title, title.get_rect(center=(512, 220)))
            surface.blit(subtitle, subtitle.get_rect(center=(512, 326)))
        else:  # dark laminate used by shelf backs and endcaps
            size = (512, 256)
            surface = pygame.Surface(size, pygame.SRCALPHA)
            surface.fill((35, 31, 27, 255))
            for y in range(0, 256, 7):
                shade = 38 + ((y * 17) % 18)
                pygame.draw.line(surface, (shade, shade - 4, shade - 8, 255), (0, y), (512, y), 2)
            pygame.draw.rect(surface, (16, 29, 84, 255), (0, 0, 512, 18))
            pygame.draw.rect(surface, (246, 214, 42, 255), (0, 18, 512, 5))
        return self._texture_from_surface(key, surface, size)

    def _load_obj_stream(
        self,
        key: str,
        model_path: Path,
    ) -> list[tuple[float, float, float, float, float, str]]:
        """Load a small OBJ into a triangle stream.

        The importer deliberately supports only the portable subset emitted
        by PulseArc's offline asset-preparation tool. Keeping it here avoids
        adding a 3D engine or a heavy model-loading dependency at runtime.
        """
        if key in self.model_meshes:
            return self.model_meshes[key]
        vertices: list[tuple[float, float, float]] = []
        texcoords: list[tuple[float, float]] = []
        triangles: list[tuple[float, float, float, float, float, str]] = []
        material = ""
        try:
            lines = model_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            self.model_meshes[key] = triangles
            return triangles
        for line in lines:
            if line.startswith("v "):
                fields = line.split()
                vertices.append((float(fields[1]), float(fields[2]), float(fields[3])))
            elif line.startswith("vt "):
                fields = line.split()
                texcoords.append((float(fields[1]), float(fields[2])))
            elif line.startswith("usemtl "):
                material = line.split(maxsplit=1)[1].strip().lower()
            elif line.startswith("f "):
                corners: list[tuple[int, int]] = []
                for field in line.split()[1:]:
                    values = field.split("/")
                    vertex_index = int(values[0])
                    texture_index = int(values[1]) if len(values) > 1 and values[1] else 0
                    if vertex_index < 0:
                        vertex_index = len(vertices) + vertex_index + 1
                    if texture_index < 0:
                        texture_index = len(texcoords) + texture_index + 1
                    corners.append((vertex_index - 1, texture_index - 1))
                for offset in range(1, len(corners) - 1):
                    for vertex_index, texture_index in (corners[0], corners[offset], corners[offset + 1]):
                        vx, vy, vz = vertices[vertex_index]
                        u, v = texcoords[texture_index] if 0 <= texture_index < len(texcoords) else (0.0, 0.0)
                        triangles.append((vx, vy, vz, u, v, material))
        self.model_meshes[key] = triangles
        return triangles

    def _community_model_path(self, group: str, name: str) -> Path:
        return (
            Path(__file__).resolve().parent / "assets" / "models" /
            "pulsearc-community" / group / f"{name}.obj"
        )

    def _load_mtl_colors(self, key: str, model_path: Path) -> dict[str, tuple[float, float, float, float]]:
        if key in self.model_materials:
            return self.model_materials[key]
        colors: dict[str, tuple[float, float, float, float]] = {}
        material = ""
        try:
            lines = model_path.with_suffix(".mtl").read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            self.model_materials[key] = colors
            return colors
        for line in lines:
            if line.startswith("newmtl "):
                material = line.split(maxsplit=1)[1].strip().lower()
            elif line.startswith("Kd ") and material:
                fields = line.split()
                if len(fields) >= 4:
                    colors[material] = (float(fields[1]), float(fields[2]), float(fields[3]), 1.0)
        self.model_materials[key] = colors
        return colors

    def _community_model(
        self, group: str, name: str
    ) -> tuple[
        list[tuple[float, float, float, float, float, str]],
        dict[str, tuple[float, float, float, float]],
    ]:
        model_path = self._community_model_path(group, name)
        key = f"community:{group}:{name}"
        return self._load_obj_stream(key, model_path), self._load_mtl_colors(key, model_path)

    def _vehicle_model(
        self,
        name: str,
        x: float,
        y: float,
        yaw: float = 0.0,
        body_color: tuple[float, float, float, float] = (0.22, 0.48, 0.82, 1.0),
    ) -> None:
        mesh, colors = self._community_model("passenger-cars", name)
        if not mesh:
            return
        glPushMatrix()
        glTranslatef(x, y, 0.03)
        glRotatef(yaw, 0.0, 0.0, 1.0)
        glScalef(0.92, 0.92, 0.92)
        glDisable(GL_TEXTURE_2D)
        glBegin(GL_TRIANGLES)
        current_material = ""
        for vx, vy, vz, _u, _v, material in mesh:
            if material != current_material:
                if "body" in material:
                    glColor4f(*body_color)
                else:
                    glColor4f(*colors.get(material, (0.44, 0.47, 0.52, 1.0)))
                current_material = material
            # Prepared community models are Y-up; PulseArc is Z-up.
            glVertex3f(vx, vz, vy)
        glEnd()
        glPopMatrix()

    def _static_community_model(
        self,
        group: str,
        name: str,
        x: float,
        y: float,
        z: float,
        yaw: float = 0.0,
        scale: float = 1.0,
        color_override: tuple[float, float, float, float] | None = None,
        material_textures: dict[str, str] | None = None,
    ) -> None:
        """Draw a prepared model while the static Plaza list is compiled."""
        model_path = (
            Path(__file__).resolve().parent / "assets" / "models" /
            group / f"{name}.obj"
        )
        mesh, colors = self._community_model(group, name)
        if not mesh:
            return
        glPushMatrix()
        glTranslatef(x, y, z)
        glRotatef(yaw, 0.0, 0.0, 1.0)
        glScalef(scale, scale, scale)
        glDisable(GL_TEXTURE_2D)
        drawing = False
        current_material = ""
        for vx, vy, vz, u, v, material in mesh:
            if material != current_material:
                if drawing:
                    glEnd()
                material_key = material.split("_material", 1)[0]
                texture_name = (material_textures or {}).get(material_key)
                texture_path = model_path.with_name(texture_name) if texture_name else None
                if texture_path is not None and texture_path.is_file():
                    texture_key = f"static:{group}:{name}:{texture_name}"
                    try:
                        surface = pygame.image.load(texture_path)
                        texture = self._texture_from_surface(
                            texture_key, surface, surface.get_size()
                        )
                    except (OSError, pygame.error):
                        texture = self._material_texture("pet-colormap")
                    glEnable(GL_TEXTURE_2D)
                    glBindTexture(GL_TEXTURE_2D, texture)
                    glColor4f(1.0, 1.0, 1.0, 1.0)
                else:
                    glDisable(GL_TEXTURE_2D)
                    glColor4f(*(color_override or colors.get(
                        material, (0.42, 0.45, 0.52, 1.0)
                    )))
                glBegin(GL_TRIANGLES)
                drawing = True
                current_material = material
            glTexCoord2f(u, v)
            glVertex3f(vx, vz, vy)
        if drawing:
            glEnd()
        glDisable(GL_TEXTURE_2D)
        glPopMatrix()

    def _dvd_case_model(self, x: float, y: float, z: float, yaw: float) -> None:
        """Place the prepared DVD case shell behind one cover image.

        This runs while ``case_scene`` is compiled, so the 451-triangle case
        geometry is uploaded once and does not add Python work per frame.
        The source model is Y-up and much deeper than a real shelf case; the
        non-uniform transform restores a 129 x 184 mm-style case proportion.
        """
        mesh, colors = self._community_model("dvd-case", "case")
        if not mesh:
            return
        glPushMatrix()
        glTranslatef(x, y, z + 0.25)
        glRotatef(yaw, 0.0, 0.0, 1.0)
        glRotatef(90.0, 1.0, 0.0, 0.0)
        glScalef(0.76, 1.92, 1.30)
        glDisable(GL_TEXTURE_2D)
        glBegin(GL_TRIANGLES)
        current_material = ""
        for vx, vy, vz, _u, _v, material in mesh:
            if material != current_material:
                glColor4f(*colors.get(material, (0.06, 0.06, 0.075, 1.0)))
                current_material = material
            glVertex3f(vx, vz, vy)
        glEnd()
        glPopMatrix()

    def _moving_model(
        self,
        model_group: str,
        name: str,
        x: float,
        y: float,
        yaw: float,
        scale: float,
        color: tuple[float, float, float, float] | None = None,
        bob: float = 0.0,
        texture_name: str | None = None,
        sway: float = 0.0,
    ) -> None:
        model_path = (
            Path(__file__).resolve().parent / "assets" / "models" /
            model_group / f"{name}.obj"
        )
        mesh = self._load_obj_stream(f"{model_group}:{name}", model_path)
        if not mesh:
            return
        # Animated actors move every frame, but their geometry never changes.
        # Compile each OBJ once so older APUs only submit one display-list call
        # per visible actor instead of thousands of Python/OpenGL calls.
        list_key = f"moving:{model_group}:{name}:{color}"
        model_list = self.model_lists.get(list_key)
        if model_list is None:
            model_list = int(glGenLists(1))
            glNewList(model_list, GL_COMPILE)
            glBegin(GL_TRIANGLES)
            shirt = color or (0.22, 0.58, 0.90, 1.0)
            material_colors = {
                "skin": (0.72, 0.49, 0.34, 1.0),
                "face": (0.78, 0.56, 0.42, 1.0),
                "shirt": shirt,
                "pants": (0.10, 0.18, 0.34, 1.0),
                "belt": (0.20, 0.10, 0.045, 1.0),
                "hair": (0.12, 0.065, 0.035, 1.0),
                "shoes": (0.08, 0.07, 0.065, 1.0),
            }
            current_material = ""
            for vx, vy, vz, u, v, material in mesh:
                if color is not None and material != current_material:
                    glColor4f(*material_colors.get(material, (0.50, 0.54, 0.62, 1.0)))
                    current_material = material
                glTexCoord2f(u, v)
                glVertex3f(vx, vz, vy)
            glEnd()
            glEndList()
            self.model_lists[list_key] = model_list
        glPushMatrix()
        glTranslatef(x, y, bob)
        glRotatef(yaw, 0.0, 0.0, 1.0)
        glRotatef(sway, 1.0, 0.0, 0.0)
        glScalef(scale, scale, scale)
        texture_path = model_path.with_name(texture_name) if texture_name else None
        if texture_path is not None and texture_path.is_file():
            texture_key = f"actor:{model_group}:{name}:{texture_name}"
            try:
                actor_surface = pygame.image.load(texture_path)
                texture = self._texture_from_surface(texture_key, actor_surface, actor_surface.get_size())
            except (OSError, pygame.error):
                texture = self._material_texture("pet-colormap")
            glEnable(GL_TEXTURE_2D)
            glBindTexture(GL_TEXTURE_2D, texture)
            glColor4f(1.0, 1.0, 1.0, 1.0)
        elif color is None:
            glEnable(GL_TEXTURE_2D)
            glBindTexture(GL_TEXTURE_2D, self._material_texture("pet-colormap"))
            glColor4f(1.0, 1.0, 1.0, 1.0)
        else:
            glDisable(GL_TEXTURE_2D)
            glColor4f(*color)
        glCallList(model_list)
        glDisable(GL_TEXTURE_2D)
        glPopMatrix()

    @staticmethod
    def _route_position(
        route: tuple[tuple[float, float], tuple[float, float]],
        phase: float,
        speed: float,
        now: float,
    ) -> tuple[float, float, float, float]:
        raw = (now * speed + phase) % 2.0
        progress = raw if raw <= 1.0 else 2.0 - raw
        (x1, y1), (x2, y2) = route
        x = x1 + (x2 - x1) * progress
        y = y1 + (y2 - y1) * progress
        direction = 1.0 if raw <= 1.0 else -1.0
        yaw = math.degrees(math.atan2((y2 - y1) * direction, (x2 - x1) * direction)) - 90.0
        step = abs(math.sin(now * speed * 18.0 + phase * 4.0))
        return x, y, yaw, step

    def _plaza_life(self) -> None:
        """Animate a lightweight random crowd and a few pets in the Plaza."""
        now = time.monotonic()
        for person in self.plaza_people:
            x, y, yaw, step = self._route_position(
                person["route"], float(person["phase"]), float(person["speed"]), now
            )
            if (x - self.player[0]) ** 2 + (y - self.player[1]) ** 2 > 30.0 ** 2:
                continue
            self._moving_model(
                str(person["group"]), str(person["model"]), x, y, yaw, float(person["scale"]),
                person["color"], 0.055 * step, person.get("texture"),
                (step - 0.5) * 5.0,
            )
        for pet in self.plaza_pets:
            x, y, yaw, step = self._route_position(
                pet["route"], float(pet["phase"]), float(pet["speed"]), now
            )
            if (x - self.player[0]) ** 2 + (y - self.player[1]) ** 2 > 27.0 ** 2:
                continue
            self._moving_model(
                str(pet["group"]), str(pet["model"]), x, y, yaw, float(pet["scale"]),
                None, 0.038 * step, pet.get("texture"),
                (step - 0.5) * 2.5,
            )

    @staticmethod
    def _textured_quad(
        texture: int,
        points: tuple[tuple[float, float, float], ...],
        uv_scale: tuple[float, float] = (1.0, 1.0),
    ) -> None:
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, texture)
        glColor4f(1.0, 1.0, 1.0, 1.0)
        glBegin(GL_QUADS)
        u_scale, v_scale = uv_scale
        for uv, point in zip(((0, 0), (u_scale, 0), (u_scale, v_scale), (0, v_scale)), points):
            glTexCoord2f(*uv)
            glVertex3f(*point)
        glEnd()
        glDisable(GL_TEXTURE_2D)

    def _room(self) -> None:
        # Carpet, ceiling, and walls.
        self._box(0, ROOM_WIDTH, 0, self.room_depth, -0.08, 0, BLACK)
        self._box(0, ROOM_WIDTH, 0, self.room_depth, ROOM_HEIGHT, ROOM_HEIGHT + 0.06, (0.68, 0.67, 0.61, 1))
        self._box(0, 0.12, 0, self.room_depth, 0, ROOM_HEIGHT, YELLOW)
        self._box(ROOM_WIDTH - 0.12, ROOM_WIDTH, 0, self.room_depth, 0, ROOM_HEIGHT, YELLOW)
        self._box(0, ROOM_WIDTH, self.room_depth - 0.12, self.room_depth, 0, ROOM_HEIGHT, YELLOW)
        # Front yellow wall segments surrounding a wide glass storefront.
        self._box(0, 5.2, 0, 0.14, 0, ROOM_HEIGHT, YELLOW)
        self._box(16.8, ROOM_WIDTH, 0, 0.14, 0, ROOM_HEIGHT, YELLOW)
        self._box(5.2, 16.8, 0, 0.14, 3.25, ROOM_HEIGHT, YELLOW)

        # Material overlays add detail without raising scene geometry cost.
        floor_texture = self._material_texture("carpet")
        self._textured_quad(floor_texture, ((0, 0, 0.004), (ROOM_WIDTH, 0, 0.004),
                                             (ROOM_WIDTH, self.room_depth, 0.004), (0, self.room_depth, 0.004)),
                            (ROOM_WIDTH / 3.0, self.room_depth / 3.0))
        ceiling_texture = self._material_texture("ceiling")
        self._textured_quad(ceiling_texture, ((0, self.room_depth, ROOM_HEIGHT - 0.005),
                                               (ROOM_WIDTH, self.room_depth, ROOM_HEIGHT - 0.005),
                                               (ROOM_WIDTH, 0, ROOM_HEIGHT - 0.005),
                                               (0, 0, ROOM_HEIGHT - 0.005)),
                            (ROOM_WIDTH / 2.0, self.room_depth / 2.0))
        wall_texture = self._material_texture("wall")
        self._textured_quad(wall_texture, ((0.125, 0, 0), (0.125, self.room_depth, 0),
                                           (0.125, self.room_depth, ROOM_HEIGHT), (0.125, 0, ROOM_HEIGHT)),
                            (self.room_depth / 2.0, ROOM_HEIGHT / 2.0))
        self._textured_quad(wall_texture, ((ROOM_WIDTH - 0.125, self.room_depth, 0),
                                           (ROOM_WIDTH - 0.125, 0, 0),
                                           (ROOM_WIDTH - 0.125, 0, ROOM_HEIGHT),
                                           (ROOM_WIDTH - 0.125, self.room_depth, ROOM_HEIGHT)),
                            (self.room_depth / 2.0, ROOM_HEIGHT / 2.0))
        self._textured_quad(wall_texture, ((ROOM_WIDTH, self.room_depth - 0.125, 0),
                                           (0, self.room_depth - 0.125, 0),
                                           (0, self.room_depth - 0.125, ROOM_HEIGHT),
                                           (ROOM_WIDTH, self.room_depth - 0.125, ROOM_HEIGHT)),
                            (ROOM_WIDTH / 2.0, ROOM_HEIGHT / 2.0))
        wall_blue = self._material_texture("wall-blue")
        band_height = 0.62
        self._textured_quad(wall_blue, ((0.12, 0, 0.02), (0.12, self.room_depth, 0.02),
                                        (0.12, self.room_depth, band_height), (0.12, 0, band_height)),
                            (self.room_depth / 1.4, 1.0))
        self._textured_quad(wall_blue, ((ROOM_WIDTH - 0.12, self.room_depth, 0.02),
                                        (ROOM_WIDTH - 0.12, 0, 0.02),
                                        (ROOM_WIDTH - 0.12, 0, band_height),
                                        (ROOM_WIDTH - 0.12, self.room_depth, band_height)),
                            (self.room_depth / 1.4, 1.0))
        self._textured_quad(wall_blue, ((ROOM_WIDTH, self.room_depth - 0.12, 0.02),
                                        (0, self.room_depth - 0.12, 0.02),
                                        (0, self.room_depth - 0.12, band_height),
                                        (ROOM_WIDTH, self.room_depth - 0.12, band_height)),
                            (ROOM_WIDTH / 1.4, 1.0))
        rug_texture = self._material_texture("rug")
        self._textured_quad(rug_texture, ((7.2, 0.72, 0.012), (14.8, 0.72, 0.012),
                                          (14.8, 4.65, 0.012), (7.2, 4.65, 0.012)))

        # Glass panels and double doors, including strong black frames.
        # The storefront is real open geometry now. Do not put a flat parking
        # photo on these panes: OpenGL would show it from both directions and
        # hide the actual store when the player is outside in the Plaza.
        for x in (5.2, 7.6, 9.7, 11.0, 12.3, 14.4, 16.8):
            self._box(x - 0.045, x + 0.045, 0.09, 0.18, 0.05, 3.3, (0.025, 0.03, 0.045, 1))
        self._box(5.2, 16.8, 0.09, 0.18, 2.35, 2.45, (0.025, 0.03, 0.045, 1))
        self._box(9.72, 9.81, 0.0, 0.28, 0.1, 2.45, (0.025, 0.03, 0.045, 1))
        self._box(12.19, 12.28, 0.0, 0.28, 0.1, 2.45, (0.025, 0.03, 0.045, 1))
        # Yellow lower panels make the storefront windows unmistakable while
        # leaving the center double-door opening clear and walkable.
        self._box(5.22, 9.68, 0.085, 0.205, 0.04, 0.58, YELLOW)
        self._box(12.32, 16.78, 0.085, 0.205, 0.04, 0.58, YELLOW)
        # Keep the panes optically open. The frames and collision boundary
        # communicate the storefront edge without hiding the outdoor Plaza.

        # Fluorescent fixtures in a ceiling grid.
        for y_index in range(3, int(self.room_depth - 1), 5):
            y = float(y_index)
            for x in (3.2, 8.4, 13.6, 18.8):
                # A wide, translucent halo below each fixture creates a soft
                # fluorescent glow even on the fixed-function rendering path.
                self._box(x - 1.12, x + 1.12, y - 0.28, y + 0.28,
                          ROOM_HEIGHT - 0.115, ROOM_HEIGHT - 0.105,
                          (1.0, 0.98, 0.72, 0.22))
                self._box(x - 0.75, x + 0.75, y - 0.12, y + 0.12, ROOM_HEIGHT - 0.08, ROOM_HEIGHT - 0.02,
                          (1.0, 0.99, 0.83, 1))

    def _front_desks(self) -> None:
        """White rental counters in both front corners of the store."""
        white = (0.90, 0.93, 0.96, 1.0)
        blue_trim = (0.05, 0.20, 0.63, 1.0)
        for x1, x2 in ((1.15, 4.85), (17.15, 20.85)):
            self._box(x1, x2, 1.15, 2.35, 0.0, 1.02, white)
            self._box(x1 - 0.05, x2 + 0.05, 1.10, 2.40, 1.02, 1.12, white)
            self._box(x1 + 0.12, x2 - 0.12, 1.08, 1.14, 0.18, 0.82, blue_trim)
            self._box(x1 + 0.28, x1 + 0.82, 1.02, 1.09, 0.43, 0.76, (0.02, 0.03, 0.05, 1.0))
            # Register, customer display, receipt printer, and card terminal.
            register_x = (x1 + x2) / 2.0
            self._box(register_x - 0.42, register_x + 0.42, 1.42, 1.88, 1.12, 1.28,
                      (0.15, 0.17, 0.21, 1.0))
            self._box(register_x - 0.32, register_x + 0.32, 1.60, 1.78, 1.28, 1.68,
                      (0.035, 0.045, 0.07, 1.0))
            self._box(register_x - 0.25, register_x + 0.25, 1.575, 1.595, 1.34, 1.60,
                      (0.14, 0.62, 0.88, 1.0))
            self._box(register_x + 0.53, register_x + 0.82, 1.43, 1.72, 1.12, 1.25,
                      (0.08, 0.09, 0.12, 1.0))

        # Monika statues flank the front registers without narrowing the
        # center entrance. Both meshes are part of the static scene list, so
        # the pair adds no Python-side geometry work during normal frames.
        monika_textures = {
            key: f"monika-{key}.png" for key in (
                "hair05", "blazer", "blazercollar", "hands", "shoe01",
                "eyelash", "eyeswhites", "eyes", "shirt", "ribbonhead",
                "hair03", "hair02", "hair01", "shoe02", "skirt",
                "highlights", "hair04", "face", "eyebrow", "legs",
                "sweater", "ribbon",
            )
        }
        for x, yaw in ((5.35, 18.0), (16.65, -18.0)):
            self._box(x - 0.46, x + 0.46, 2.55, 3.35, 0.0, 0.34,
                      (0.035, 0.13, 0.48, 1.0))
            self._box(x - 0.52, x + 0.52, 2.49, 3.41, 0.34, 0.43,
                      (0.98, 0.78, 0.08, 1.0))
            self._static_community_model(
                "pulsearc-local", "monika", x, 2.95, 0.43, yaw, 0.70,
                material_textures=monika_textures,
            )

    def _tree(self, x: float, y: float, scale: float = 1.0) -> None:
        self._box(x - 0.13 * scale, x + 0.13 * scale, y - 0.13 * scale, y + 0.13 * scale,
                  0.0, 2.2 * scale, (0.30, 0.17, 0.075, 1.0))
        greens = ((0.07, 0.36, 0.13, 1.0), (0.10, 0.48, 0.17, 1.0), (0.16, 0.58, 0.20, 1.0))
        for index, (ox, oy, oz) in enumerate(((0, 0, 2.5), (-0.65, 0.1, 2.25),
                                               (0.62, 0.18, 2.32), (0.0, -0.55, 2.18),
                                               (0.0, 0.48, 2.42))):
            radius = (0.78 if index else 1.0) * scale
            self._box(x + ox * scale - radius, x + ox * scale + radius,
                      y + oy * scale - radius, y + oy * scale + radius,
                      (oz - 0.55) * scale, (oz + 0.55) * scale, greens[index % len(greens)])

    def _internet_cafe(self) -> None:
        """Build a walk-in retro Internet Cafe from cached low-poly assets."""
        floor = (0.055, 0.065, 0.10, 1.0)
        wall = (0.07, 0.19, 0.28, 1.0)
        trim = (0.06, 0.78, 0.86, 1.0)
        desk = (0.28, 0.14, 0.065, 1.0)
        # Shell: the west wall faces the parking lot and has a wide open door.
        self._box(30.2, 40.0, -31.0, -4.0, 0.0, 0.08, floor)
        self._box(39.84, 40.0, -31.0, -4.0, 0.0, 4.5, wall)
        self._box(30.2, 40.0, -31.0, -30.84, 0.0, 4.5, wall)
        self._box(30.2, 40.0, -4.16, -4.0, 0.0, 4.5, wall)
        self._box(30.2, 30.36, -31.0, -20.3, 0.0, 4.5, wall)
        self._box(30.2, 30.36, -14.7, -4.0, 0.0, 4.5, wall)
        self._box(30.2, 30.36, -20.3, -14.7, 3.05, 4.5, wall)
        self._box(30.2, 40.0, -31.0, -4.0, 4.42, 4.50, (0.17, 0.20, 0.24, 1.0))
        self._box(30.18, 30.40, -20.3, -20.12, 0.0, 3.05, trim)
        self._box(30.18, 30.40, -14.88, -14.7, 0.0, 3.05, trim)
        self._box(30.18, 30.40, -20.3, -14.7, 2.92, 3.08, trim)

        # Four computer stations face inward. Imported geometry is submitted
        # only while the static display list is being compiled.
        station_y = (-9.0, -14.2, -22.0, -27.2)
        pc_names = ("retro-pc-cream", "retro-pc-black", "retro-pc-white", "retro-pc-cream")
        for y, pc_name in zip(station_y, pc_names):
            self._box(35.0, 39.0, y - 0.70, y + 0.70, 0.02, 0.78, desk)
            self._box(35.0, 35.18, y - 0.70, y + 0.70, 0.0, 0.76, (0.13, 0.07, 0.035, 1.0))
            self._box(38.82, 39.0, y - 0.70, y + 0.70, 0.0, 0.76, (0.13, 0.07, 0.035, 1.0))
            self._static_community_model("retro-office", pc_name, 37.0, y, 0.80, 90.0, 0.78)
            self._static_community_model("retro-office", "office-chair", 33.9, y, 0.02, -90.0, 0.78)
        self._static_community_model("retro-office", "water-cooler", 38.8, -18.0, 0.02, 180.0, 0.90)
        cafe_sign = self._text_texture("PULSEARC NET CAFE")
        self._textured_quad(cafe_sign, ((39.82, -24.0, 2.4), (39.82, -11.0, 2.4),
                                        (39.82, -11.0, 3.35), (39.82, -24.0, 3.35)))

    def _plaza(self) -> None:
        """Draw the outdoor hub with four readable destination storefronts."""
        asphalt = (0.075, 0.082, 0.10, 1.0)
        concrete = (0.48, 0.50, 0.54, 1.0)
        curb = (0.82, 0.82, 0.76, 1.0)
        self._box(PLAZA_MIN_X, PLAZA_MAX_X, PLAZA_MIN_Y, 0.0, -0.12, -0.02, asphalt)
        asphalt_texture = self._material_texture("plaza-asphalt")
        self._textured_quad(
            asphalt_texture,
            ((PLAZA_MIN_X, PLAZA_MIN_Y, -0.015), (PLAZA_MAX_X, PLAZA_MIN_Y, -0.015),
             (PLAZA_MAX_X, 0.0, -0.015), (PLAZA_MIN_X, 0.0, -0.015)),
            (7.0, 5.0),
        )
        sky = self._material_texture("plaza-sky")
        # Lightweight panoramic backdrop: three distant planes give the lot
        # sky, mountains, and a horizon without shader-heavy HDR rendering.
        self._textured_quad(sky, ((PLAZA_MIN_X, PLAZA_MIN_Y + 0.05, 0.0),
                                  (PLAZA_MAX_X, PLAZA_MIN_Y + 0.05, 0.0),
                                  (PLAZA_MAX_X, PLAZA_MIN_Y + 0.05, 14.0),
                                  (PLAZA_MIN_X, PLAZA_MIN_Y + 0.05, 14.0)))
        self._textured_quad(sky, ((PLAZA_MIN_X + 0.05, 0.0, 0.0),
                                  (PLAZA_MIN_X + 0.05, PLAZA_MIN_Y, 0.0),
                                  (PLAZA_MIN_X + 0.05, PLAZA_MIN_Y, 14.0),
                                  (PLAZA_MIN_X + 0.05, 0.0, 14.0)))
        self._textured_quad(sky, ((PLAZA_MAX_X - 0.05, PLAZA_MIN_Y, 0.0),
                                  (PLAZA_MAX_X - 0.05, 0.0, 0.0),
                                  (PLAZA_MAX_X - 0.05, 0.0, 14.0),
                                  (PLAZA_MAX_X - 0.05, PLAZA_MIN_Y, 14.0)))
        # Complete the GameBuster/storefront side without covering the shop:
        # side panels flank the building and a header fills only above its roof.
        self._textured_quad(sky, ((PLAZA_MIN_X, -0.04, 0.0),
                                  (0.0, -0.04, 0.0),
                                  (0.0, -0.04, 14.0),
                                  (PLAZA_MIN_X, -0.04, 14.0)))
        self._textured_quad(sky, ((ROOM_WIDTH, -0.04, 0.0),
                                  (PLAZA_MAX_X, -0.04, 0.0),
                                  (PLAZA_MAX_X, -0.04, 14.0),
                                  (ROOM_WIDTH, -0.04, 14.0)))
        # A separate cloud-only texture closes the top of the outdoor scene;
        # the mountain horizon belongs on the side walls, never overhead.
        sky_top = self._material_texture("plaza-sky-top")
        self._textured_quad(sky_top, ((0.0, -0.04, ROOM_HEIGHT + 0.06),
                                      (ROOM_WIDTH, -0.04, ROOM_HEIGHT + 0.06),
                                      (ROOM_WIDTH, -0.04, 14.0),
                                      (0.0, -0.04, 14.0)))
        self._textured_quad(
            sky_top,
            ((PLAZA_MIN_X, 0.0, 14.05), (PLAZA_MAX_X, 0.0, 14.05),
             (PLAZA_MAX_X, PLAZA_MIN_Y, 14.05), (PLAZA_MIN_X, PLAZA_MIN_Y, 14.05)),
            (2.0, 2.0),
        )
        self._box(-1.0, 23.0, -4.2, -0.18, -0.015, 0.035, concrete)
        self._box(-18.0, -7.8, -31.0, -4.0, -0.02, 0.04, concrete)
        self._box(29.8, 40.2, -31.0, -4.0, -0.02, 0.04, concrete)
        self._box(3.2, 18.8, -32.0, -28.7, -0.02, 0.04, concrete)

        for x in range(-5, 30, 3):
            self._box(float(x), float(x) + 0.08, -18.5, -10.0, -0.005, 0.012, curb)
            self._box(float(x), float(x) + 0.08, -28.0, -20.0, -0.005, 0.012, curb)
        for y in (-18.5, -10.0, -28.0, -20.0):
            self._box(-5.0, 29.0, y, y + 0.08, -0.005, 0.012, curb)

        self._box(-18.0, -8.2, -31.0, -4.0, 0.0, 5.2, (0.19, 0.12, 0.26, 1.0))
        self._internet_cafe()
        self._box(3.5, 18.5, -39.0, -29.0, 0.0, 5.6, (0.12, 0.14, 0.22, 1.0))
        # User-supplied outdoor court occupies the expanded west plaza. It is
        # submitted only while the static scene display list is compiled.
        self._static_community_model(
            "pulsearc-local", "basketball-court", -31.0, -19.0, 0.01, 0.0, 1.0
        )
        self._box(-8.25, -8.05, -20.0, -14.5, 0.0, 3.5, (0.04, 0.05, 0.08, 1.0))
        self._box(30.05, 30.25, -20.0, -14.5, 0.0, 3.5, (0.04, 0.05, 0.08, 1.0))
        self._box(8.0, 14.0, -29.15, -28.95, 0.0, 4.0, (0.04, 0.05, 0.08, 1.0))

        side_signs = (
            ("MOVIE THEATER", -8.01, -23.2, -11.2, 3.75, 4.55),
            ("INTERNET CAFE", 30.01, -11.2, -23.2, 3.35, 4.15),
        )
        for label, x, y1, y2, z1, z2 in side_signs:
            texture = self._text_texture(label)
            self._textured_quad(texture, ((x, y1, z1), (x, y2, z1), (x, y2, z2), (x, y1, z2)))
        video_texture = self._text_texture("GAMEBUSTER")
        self._textured_quad(video_texture, ((4.4, -0.19, 3.35), (17.6, -0.19, 3.35),
                                             (17.6, -0.19, 4.05), (4.4, -0.19, 4.05)))
        # This storefront faces the Plaza, so reverse the former back-facing
        # vertex order that made its text read as a mirror image.
        arcade_texture = self._text_texture("PULSE ARCADE")
        self._textured_quad(arcade_texture, ((17.0, -28.91, 4.25), (5.0, -28.91, 4.25),
                                              (5.0, -28.91, 5.05), (17.0, -28.91, 5.05)))

        parking_spaces = (
            (-4.0, -14.3, 0.0), (2.5, -14.3, 0.0), (9.0, -14.3, 0.0),
            (15.5, -14.3, 0.0), (22.0, -14.3, 0.0), (28.0, -14.3, 0.0),
            (-3.0, -24.1, 180.0), (3.5, -24.1, 180.0), (10.0, -24.1, 180.0),
            (16.5, -24.1, 180.0), (23.0, -24.1, 180.0), (28.0, -24.1, 180.0),
        )
        for model, color, (x, y, yaw) in zip(self.parked_models, self.parked_colors, parking_spaces):
            self._vehicle_model(model, x, y, yaw, color)
        for x, y, scale in (
            (-15.0, -7.0, 1.0), (-15.0, -27.0, 1.15), (37.0, -8.0, 1.0),
            (37.0, -27.0, 1.1), (-6.0, -35.0, 0.95), (28.0, -35.0, 1.0),
        ):
            self._tree(x, y, scale)
        for x, y in ((-2.0, -6.0), (24.0, -6.0), (-4.0, -31.5), (26.0, -31.5)):
            self._box(x - 0.07, x + 0.07, y - 0.07, y + 0.07, 0.0, 4.5, (0.10, 0.11, 0.14, 1.0))
            self._box(x - 0.42, x + 0.42, y - 0.22, y + 0.22, 4.35, 4.55, (1.0, 0.91, 0.55, 1.0))

    def _parked_car(self, x: float, y: float, color: tuple[float, float, float, float]) -> None:
        self._box(x, x + 2.25, y, y + 4.1, 0.08, 0.72, color)
        self._box(x + 0.30, x + 1.95, y + 0.85, y + 3.15, 0.72, 1.28, color)
        glass = (0.05, 0.10, 0.15, 1.0)
        self._box(x + 0.38, x + 1.87, y + 0.78, y + 0.88, 0.77, 1.17, glass)
        self._box(x + 0.38, x + 1.87, y + 3.12, y + 3.22, 0.77, 1.17, glass)
        for wx in (x + 0.12, x + 1.83):
            for wy in (y + 0.65, y + 3.15):
                self._box(wx, wx + 0.30, wy, wy + 0.22, 0.0, 0.40, (0.015, 0.018, 0.022, 1.0))

    def _cashiers(self) -> None:
        """Animate two lightweight clerks behind the front counters."""
        now = time.monotonic()
        for index, x in enumerate((3.0, 19.0)):
            bob = math.sin(now * 2.1 + index * 1.7) * 0.025
            wave = math.sin(now * 3.0 + index * 2.2) * 0.16
            y = 0.78
            self._box(x - 0.28, x + 0.28, y - 0.18, y + 0.18, 1.02 + bob, 1.82 + bob,
                      (0.08, 0.22, 0.62, 1.0))
            self._box(x - 0.23, x + 0.23, y - 0.16, y + 0.16, 1.82 + bob, 2.24 + bob,
                      (0.78, 0.56, 0.40, 1.0))
            self._box(x - 0.52, x - 0.30, y - 0.12, y + 0.12, 1.18 + bob, 1.72 + bob + wave,
                      (0.78, 0.56, 0.40, 1.0))
            self._box(x + 0.30, x + 0.52, y - 0.12, y + 0.12, 1.18 + bob, 1.72 + bob - wave,
                      (0.78, 0.56, 0.40, 1.0))

    def _start_lounge_music(self) -> None:
        self.lounge_tracks: list[Path] = []
        self.lounge_index = -1
        self.lounge_end_event = pygame.USEREVENT + 4
        if self.self_test:
            return
        asset_root = Path(__file__).resolve().parent / "assets"
        self.lounge_tracks = sorted(asset_root.glob("plaza-lounge-*.mp3"))
        if not self.lounge_tracks:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.set_endevent(self.lounge_end_event)
            pygame.mixer.music.set_volume(0.32)
            self._advance_lounge_music()
        except pygame.error:
            self.lounge_tracks = []

    def _advance_lounge_music(self) -> None:
        if not self.lounge_tracks:
            return
        self.lounge_index = (self.lounge_index + 1) % len(self.lounge_tracks)
        try:
            pygame.mixer.music.load(self.lounge_tracks[self.lounge_index])
            pygame.mixer.music.play()
        except pygame.error:
            pass

    def _shelves(self) -> None:
        shelf_color = (0.66, 0.66, 0.61, 1.0)
        trim_color = (0.055, 0.19, 0.61, 1.0)

        # Open-backed perimeter racks: thin shelves and uprights leave visible
        # wall between fixtures instead of forming implausible solid blocks.
        wall_start, wall_end = 5.0, self.room_depth - 1.15
        shelf_levels = (0.12, 0.58, 1.04, 1.50, 1.96, 2.42)
        for left_side in (True, False):
            x1, x2 = ((0.18, 0.72) if left_side else (ROOM_WIDTH - 0.72, ROOM_WIDTH - 0.18))
            for z in shelf_levels:
                self._box(x1, x2, wall_start, wall_end, z, z + 0.045, shelf_color)
            upright_y = wall_start
            while upright_y <= wall_end + 0.01:
                self._box(x1, x2, upright_y - 0.028, upright_y + 0.028, 0.08, 2.46, trim_color)
                upright_y += 3.2
            self._box(x1, x2, wall_start, wall_end, 0.05, 0.12, trim_color)

        back_y1, back_y2 = self.room_depth - 0.72, self.room_depth - 0.18
        for z in shelf_levels:
            self._box(1.25, ROOM_WIDTH - 1.25, back_y1, back_y2, z, z + 0.045, shelf_color)
        upright_x = 1.25
        while upright_x <= ROOM_WIDTH - 1.25 + 0.01:
            self._box(upright_x - 0.028, upright_x + 0.028, back_y1, back_y2, 0.08, 2.46, trim_color)
            upright_x += 3.25
        self._box(1.25, ROOM_WIDTH - 1.25, back_y1, back_y2, 0.05, 0.12, trim_color)

        for shelf_index, (x1, x2, shelf_y) in enumerate(self.island_shelves):
            # Short freestanding racks with three two-game bays per row.
            self._box(x1 + 0.10, x2 - 0.10, shelf_y - 0.055, shelf_y + 0.055, 0.06, 2.36, shelf_color)
            self._box(x1, x1 + 0.14, shelf_y - 0.49, shelf_y + 0.49, 0.0, 2.62, trim_color)
            self._box(x2 - 0.14, x2, shelf_y - 0.49, shelf_y + 0.49, 0.0, 2.62, trim_color)
            for z in (0.08, 0.66, 1.24, 1.82, 2.38):
                self._box(x1, x2, shelf_y - 0.50, shelf_y + 0.50, z, z + 0.065, shelf_color)
                self._box(x1, x2, shelf_y - 0.515, shelf_y - 0.495, z + 0.055, z + 0.095, YELLOW)
                self._box(x1, x2, shelf_y + 0.495, shelf_y + 0.515, z + 0.055, z + 0.095, YELLOW)
            for divider in range(4):
                x = x1 + divider * ((x2 - x1) / 3)
                self._box(x - 0.022, x + 0.022, shelf_y - 0.50, shelf_y + 0.50,
                          0.08, 2.42, (0.47, 0.48, 0.47, 1.0))

            label = self.system_labels[shelf_index] if shelf_index < len(self.system_labels) else "AVAILABLE TITLES"
            sign = self._text_texture(label)
            self._textured_quad(sign, ((x1 + 0.12, shelf_y - 0.522, 2.38),
                                       (x2 - 0.12, shelf_y - 0.522, 2.38),
                                       (x2 - 0.12, shelf_y - 0.522, 2.67),
                                       (x1 + 0.12, shelf_y - 0.522, 2.67)))
            self._textured_quad(sign, ((x2 - 0.12, shelf_y + 0.522, 2.38),
                                       (x1 + 0.12, shelf_y + 0.522, 2.38),
                                       (x1 + 0.12, shelf_y + 0.522, 2.67),
                                       (x2 - 0.12, shelf_y + 0.522, 2.67)))

            # One large, framed installed-title poster on each endcap.
            if shelf_index < len(self.island_assignments) and self.island_assignments[shelf_index][1]:
                indices = self.island_assignments[shelf_index][1]
                for side, entry_index in ((-1, indices[0]), (1, indices[-1])):
                    texture = self._cover_texture(self.entries[entry_index])
                    x = x1 - 0.006 if side < 0 else x2 + 0.006
                    points = (((x, shelf_y + 0.36, 0.62), (x, shelf_y - 0.36, 0.62),
                               (x, shelf_y - 0.36, 2.18), (x, shelf_y + 0.36, 2.18))
                              if side < 0 else
                              ((x, shelf_y - 0.36, 0.62), (x, shelf_y + 0.36, 0.62),
                               (x, shelf_y + 0.36, 2.18), (x, shelf_y - 0.36, 2.18)))
                    self._textured_quad(texture, points)

        # Original store branding and the classic rental courtesy reminder.
        sign_y = self.room_depth - 0.74
        main_sign = self._text_texture("PULSEARC VIDEO & GAMES")
        self._textured_quad(main_sign, ((4.0, sign_y, 3.15), (18.0, sign_y, 3.15),
                                        (18.0, sign_y, 3.92), (4.0, sign_y, 3.92)))
        rewind_sign = self._text_texture("PLEASE BE KIND • REWIND")
        self._textured_quad(rewind_sign, ((7.2, sign_y - 0.01, 2.58), (14.8, sign_y - 0.01, 2.58),
                                          (14.8, sign_y - 0.01, 3.02), (7.2, sign_y - 0.01, 3.02)))
        if self.vod_catalog:
            page_sign = self._text_texture(
                f"VOD NEW RELEASES  {self.vod_page + 1}/{self.vod_page_count}  -  LB/RB CHANGES SHELVES"
            )
            self._textured_quad(page_sign, ((4.3, sign_y - 0.015, 2.10), (17.7, sign_y - 0.015, 2.10),
                                             (17.7, sign_y - 0.015, 2.47), (4.3, sign_y - 0.015, 2.47)))

    def _base_cases(self) -> None:
        for x, y, z, index in self.case_positions:
            if index >= len(self.entries):
                continue
            texture = self._cover_texture(self.entries[index])
            if texture is None:
                continue
            left_wall = abs(x - 0.76) < 0.05
            right_wall = abs(x - (ROOM_WIDTH - 0.76)) < 0.05
            back_wall = abs(y - (self.room_depth - 0.76)) < 0.05
            facing_front = back_wall or any(
                abs(y - (shelf_y - 0.535)) < 0.05 for _x1, _x2, shelf_y in self.island_shelves
            )
            # The fixed-function fallback renders the model's clear plastic
            # sleeve as opaque. Place artwork just outside that sleeve to
            # retain the molded 3D case without covering the game art.
            plane_y = y - 0.040 if facing_front else y + 0.040
            # Standard DVD case artwork is approximately 129 mm × 184 mm.
            # Keep that portrait ratio in-world instead of stretching covers.
            selected = False
            half_width = 0.17 if selected else 0.14
            case_height = 0.56 if selected else 0.50
            case_bottom = z - 0.03 if selected else z
            yaw = 90.0 if left_wall else (-90.0 if right_wall else (0.0 if facing_front else 180.0))
            self._dvd_case_model(x, y, case_bottom, yaw)
            if left_wall:
                plane_x = x + 0.040
                points = ((plane_x, y - half_width, case_bottom), (plane_x, y + half_width, case_bottom),
                          (plane_x, y + half_width, case_bottom + case_height),
                          (plane_x, y - half_width, case_bottom + case_height))
            elif right_wall:
                plane_x = x - 0.040
                points = ((plane_x, y + half_width, case_bottom), (plane_x, y - half_width, case_bottom),
                          (plane_x, y - half_width, case_bottom + case_height),
                          (plane_x, y + half_width, case_bottom + case_height))
            elif facing_front:
                points = ((x - half_width, plane_y, case_bottom), (x + half_width, plane_y, case_bottom),
                          (x + half_width, plane_y, case_bottom + case_height),
                          (x - half_width, plane_y, case_bottom + case_height))
            else:
                points = ((x + half_width, plane_y, case_bottom), (x - half_width, plane_y, case_bottom),
                          (x - half_width, plane_y, case_bottom + case_height),
                          (x + half_width, plane_y, case_bottom + case_height))
            self._textured_quad(texture, points)
            if selected:
                glDisable(GL_TEXTURE_2D)
                glColor4f(1.0, 0.82, 0.05, 1.0)
                glBegin(GL_QUADS)
                glVertex3f(x - 0.21, plane_y - 0.01, z - 0.025)
                glVertex3f(x + 0.21, plane_y - 0.01, z - 0.025)
                glVertex3f(x + 0.21, plane_y - 0.01, z)
                glVertex3f(x - 0.21, plane_y - 0.01, z)
                glEnd()

    def _cases(self) -> None:
        # Shelf artwork is stationary, so draw the precompiled GPU list and
        # update only a tiny focus marker as the player aims around.
        glCallList(self.case_scene)
        if self.focus is None:
            return
        selected = next((item for item in self.case_positions if item[3] == self.focus), None)
        if selected is None:
            return
        x, y, z, _index = selected
        facing_front = any(abs(y - (shelf_y - 0.535)) < 0.05 for _x1, _x2, shelf_y in self.island_shelves)
        plane_y = y - 0.035 if facing_front else y + 0.035
        glDisable(GL_TEXTURE_2D)
        glColor4f(1.0, 0.82, 0.05, 1.0)
        glBegin(GL_QUADS)
        glVertex3f(x - 0.18, plane_y, z - 0.025)
        glVertex3f(x + 0.18, plane_y, z - 0.025)
        glVertex3f(x + 0.18, plane_y, z)
        glVertex3f(x - 0.18, plane_y, z)
        glEnd()

    def _collision_free(self, x: float, y: float) -> bool:
        if -0.85 < y < 0.75 and not 9.55 < x < 12.45:
            return False
        if y >= 0.0:
            if x < 0.55 or x > ROOM_WIDTH - 0.55 or y > self.room_depth - 0.55:
                return False
            if x < 0.95 or x > ROOM_WIDTH - 0.95 or y > self.room_depth - 0.95:
                return False
            for x1, x2, shelf_y in self.island_shelves:
                if x1 - 0.28 < x < x2 + 0.28 and shelf_y - 0.78 < y < shelf_y + 0.78:
                    return False
            for x1, x2 in ((1.15, 4.85), (17.15, 20.85)):
                if x1 - 0.25 < x < x2 + 0.25 and 0.85 < y < 2.62:
                    return False
            return True
        if not (PLAZA_MIN_X + 0.55 < x < PLAZA_MAX_X - 0.55 and PLAZA_MIN_Y + 0.55 < y):
            return False
        if -18.3 < x < -7.7 and -31.3 < y < -3.7:
            return False
        if 29.7 < x < 40.3 and -31.3 < y < -3.7:
            # Internet Cafe is walkable through its west-facing entrance.
            inside = 30.55 < x < 39.55 and -30.55 < y < -4.45
            doorway = 29.7 < x <= 30.55 and -20.1 < y < -14.9
            if not (inside or doorway):
                return False
            for station_y in (-9.0, -14.2, -22.0, -27.2):
                if 34.65 < x < 39.25 and station_y - 0.95 < y < station_y + 0.95:
                    return False
        if 3.2 < x < 18.8 and -39.3 < y < -28.6:
            return False
        return True

    def _move(self, forward: float, strafe: float, elapsed: float) -> None:
        dx = math.cos(self.angle) * forward + math.cos(self.angle + math.pi / 2) * strafe
        dy = math.sin(self.angle) * forward + math.sin(self.angle + math.pi / 2) * strafe
        nx, ny = self.player[0] + dx * elapsed, self.player[1] + dy * elapsed
        if self._collision_free(nx, self.player[1]):
            self.player[0] = nx
        if self._collision_free(self.player[0], ny):
            self.player[1] = ny

    def _update_focus(self) -> None:
        best: tuple[float, int] | None = None
        for x, y, z, index in self.case_positions:
            dx, dy = x - self.player[0], y - self.player[1]
            distance = math.hypot(dx, dy)
            horizontal_delta = abs(angle_delta(math.atan2(dy, dx) - self.angle))
            vertical_angle = math.atan2((z + 0.25) - 1.55, max(0.01, distance))
            vertical_delta = abs(vertical_angle - self.pitch)
            if distance <= 4.2 and horizontal_delta <= 0.16 and vertical_delta <= 0.15:
                score = distance * 0.05 + horizontal_delta * 4.0 + vertical_delta * 4.0
                if best is None or score < best[0]:
                    best = (score, index)
        self.focus = best[1] if best else None

    def _aim_at_case(self, selected: tuple[float, float, float, int]) -> None:
        x, y, z, index = selected
        dx, dy = x - self.player[0], y - self.player[1]
        distance = math.hypot(dx, dy)
        self.angle = math.atan2(dy, dx) % math.tau
        self.pitch = max(-0.85, min(0.85, math.atan2((z + 0.25) - 1.55, max(0.01, distance))))
        self.focus = index

    def _cycle_case(self, horizontal: int = 0, vertical: int = 0) -> None:
        nearby = [position for position in self.case_positions
                  if math.hypot(position[0] - self.player[0], position[1] - self.player[1]) <= 4.2]
        if not nearby:
            self.angle = (self.angle + horizontal * 0.20) % math.tau
            self.pitch = max(-0.85, min(0.85, self.pitch + vertical * 0.12))
            return
        current = next((item for item in nearby if item[3] == self.focus), None)
        if current is None:
            current = min(
                nearby,
                key=lambda item: (
                    abs(angle_delta(math.atan2(item[1] - self.player[1], item[0] - self.player[0]) - self.angle))
                    + abs(math.atan2((item[2] + 0.25) - 1.55,
                                     max(0.01, math.hypot(item[0] - self.player[0], item[1] - self.player[1]))) - self.pitch)
                ),
            )
        side_wall = abs(current[0] - 0.76) < 0.08 or abs(current[0] - (ROOM_WIDTH - 0.76)) < 0.08
        if side_wall:
            face = [item for item in nearby if abs(item[0] - current[0]) < 0.08]
        else:
            face_y = current[1]
            face = [item for item in nearby if abs(item[1] - face_y) < 0.08]
        levels = sorted({item[2] for item in face})
        current_level = min(range(len(levels)), key=lambda index: abs(levels[index] - current[2]))
        target_level = max(0, min(len(levels) - 1, current_level + vertical))
        row = sorted(
            (item for item in face if abs(item[2] - levels[target_level]) < 0.02),
            key=(lambda item: item[1]) if side_wall else (lambda item: item[0]),
        )
        if vertical:
            selected = min(
                row,
                key=(lambda item: abs(item[1] - current[1])) if side_wall
                else (lambda item: abs(item[0] - current[0])),
            )
        else:
            current_column = min(
                range(len(row)),
                key=(lambda index: abs(row[index][1] - current[1])) if side_wall
                else (lambda index: abs(row[index][0] - current[0])),
            )
            selected = row[(current_column + horizontal) % len(row)]
        self._aim_at_case(selected)

    def _draw_crosshair(self) -> None:
        if self.detail_index is not None:
            return
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_TEXTURE_2D)
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        glOrtho(0, self.width, 0, self.height, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glTranslatef(self.width / 2, self.height / 2, 0)
        glColor4f(1.0, 0.84, 0.12, 0.95 if self.focus is not None else 0.72)
        glCallList(self.crosshair_scene)
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
        glEnable(GL_DEPTH_TEST)

    def _events(self) -> None:
        for event in pygame.event.get():
            if hasattr(self, "lounge_end_event") and event.type == self.lounge_end_event:
                self._advance_lounge_music()
            elif event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.JOYDEVICEADDED:
                stick = pygame.joystick.Joystick(event.device_index)
                stick.init()
                self.controllers[stick.get_instance_id()] = stick
                self._configure_turn_axis(stick)
            elif event.type == pygame.JOYDEVICEREMOVED:
                self.controllers.pop(event.instance_id, None)
            elif event.type == pygame.JOYAXISMOTION and event.axis in self.axes:
                self.axes[event.axis] = float(event.value)
            elif event.type == pygame.JOYHATMOTION:
                if self.detail_index is not None:
                    continue
                if event.value[0]:
                    self._cycle_case(horizontal=event.value[0])
                if event.value[1]:
                    self._cycle_case(vertical=event.value[1])
            elif event.type == pygame.JOYBUTTONDOWN:
                if event.button == 0 and self.detail_index is not None:
                    self._select(self.detail_index, "launch")
                elif event.button == 2 and self.detail_index is not None and is_new_release(self.entries[self.detail_index]):
                    self._select(self.detail_index, "install")
                elif event.button == 0 and self.focus is not None:
                    self._ensure_vod_details(self.focus)
                    self.detail_index = self.focus
                elif event.button == 1:
                    if self.detail_index is not None:
                        self.detail_index = None
                    else:
                        self.running = False
                elif event.button == 4:
                    self._change_vod_page(-1)
                elif event.button == 5:
                    self._change_vod_page(1)
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                    if self.detail_index is not None:
                        self.detail_index = None
                    else:
                        self.running = False
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and self.detail_index is not None:
                    self._select(self.detail_index, "launch")
                elif event.key == pygame.K_i and self.detail_index is not None and is_new_release(self.entries[self.detail_index]):
                    self._select(self.detail_index, "install")
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and self.focus is not None:
                    self._ensure_vod_details(self.focus)
                    self.detail_index = self.focus
                elif event.key == pygame.K_PAGEUP:
                    self._change_vod_page(-1)
                elif event.key == pygame.K_PAGEDOWN:
                    self._change_vod_page(1)
                elif event.key == pygame.K_LEFT:
                    self._cycle_case(horizontal=-1)
                elif event.key == pygame.K_RIGHT:
                    self._cycle_case(horizontal=1)
                elif event.key == pygame.K_UP:
                    self._cycle_case(vertical=1)
                elif event.key == pygame.K_DOWN:
                    self._cycle_case(vertical=-1)

    def _select(self, index: int, action: str = "launch") -> None:
        if 0 <= index < len(self.entries):
            entry = self.entries[index]
            payload: dict[str, Any] = {
                "content_id": entry.get("content_id", ""),
                "action": "play-vod" if str(entry.get("content_id", "")) in self.vod_ids else action,
            }
            if payload["action"] == "play-vod":
                payload["media"] = {
                    "name": entry.get("title", "MOVIE"),
                    "url": entry.get("url", ""),
                    "group": entry.get("group", VOD_GROUP),
                    "logo": entry.get("cover_url", ""),
                    "stream_id": entry.get("stream_id", ""),
                    "media_type": "movie",
                    "source": entry.get("source", "XTREAM"),
                }
            self.selection_file.parent.mkdir(parents=True, exist_ok=True)
            self.selection_file.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            try:
                self.selection_file.chmod(0o600)
            except OSError:
                pass
        self.running = False

    def _save_store_state(self) -> None:
        try:
            STORE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STORE_STATE_PATH.write_text(
                json.dumps({"x": self.player[0], "y": self.player[1], "angle": self.angle}),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _render(self) -> None:
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        horizontal = math.cos(self.pitch)
        target_x = self.player[0] + math.cos(self.angle) * horizontal
        target_y = self.player[1] + math.sin(self.angle) * horizontal
        target_z = 1.55 + math.sin(self.pitch)
        gluLookAt(self.player[0], self.player[1], 1.55, target_x, target_y, target_z, 0, 0, 1)
        glCallList(self.static_scene)
        self._cases()
        self._cashiers()
        # Deep inside the store the outdoor crowd is not visible and costs no
        # render time. Near the storefront and throughout the Plaza it remains
        # active and can be seen through the open panes.
        if self.player[1] < 7.0:
            self._plaza_life()
        self._draw_crosshair()
        self._draw_detail_overlay()
        pygame.display.flip()

    def run(self) -> int:
        if self.self_test:
            self._update_focus()
            self._render()
            pygame.quit()
            print("PULSEARC_3D_PLAZA_SELF_TEST_OK")
            return 0
        while self.running:
            elapsed = min(0.05, self.clock.tick(60) / 1000.0)
            self._events()
            if self.detail_index is not None:
                self._render()
                continue
            forward = -self.axes[1] if abs(self.axes[1]) > 0.15 else 0.0
            # Raw Xbox axes are positive right; the room's strafe basis points
            # left at the starting orientation, so invert it here.
            strafe = -self.axes[0] if abs(self.axes[0]) > 0.15 else 0.0
            turn_value = self.axes.get(self.turn_axis, 0.0)
            turn = -turn_value if abs(turn_value) > 0.15 else 0.0
            pitch_value = self.axes.get(self.pitch_axis, 0.0)
            pitch = -pitch_value if abs(pitch_value) > 0.15 else 0.0
            keys = pygame.key.get_pressed()
            forward += float(keys[pygame.K_w]) - float(keys[pygame.K_s])
            strafe += float(keys[pygame.K_d]) - float(keys[pygame.K_a])
            turn += float(keys[pygame.K_RIGHT]) - float(keys[pygame.K_LEFT])
            self.angle = (self.angle + turn * 2.85 * elapsed) % math.tau
            self.pitch = max(-0.85, min(0.85, self.pitch + pitch * 1.9 * elapsed))
            self._move(forward * 5.4, strafe * 4.4, elapsed)
            self._update_focus()
            self._render()
        self._save_store_state()
        if self.static_scene:
            glDeleteLists(self.static_scene, 1)
        for model_list in self.model_lists.values():
            glDeleteLists(model_list, 1)
        if self.textures:
            glDeleteTextures(list(self.textures.values()))
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
        pygame.quit()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection-file", type=Path, default=Path("/run/pulsearc/3d-selection.json"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    return Store(args.selection_file, args.self_test).run()


if __name__ == "__main__":
    raise SystemExit(main())
