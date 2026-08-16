from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NATIVE_UI = ROOT / "native-ui"

import sys

sys.path.insert(0, str(NATIVE_UI))

from pulsearc_archive_import import (  # noqa: E402
    approved_archive,
    discover_archives,
    install_archive,
    validate_archive,
)


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as package:
        for name, payload in members.items():
            package.writestr(name, payload)
    return path


def test_discovers_supported_archives_but_not_symlinks(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    _zip(media / "game.zip", {"game.nes": b"NES\x1a"})
    (media / "notes.txt").write_text("ignore", encoding="utf-8")

    found = discover_archives((media,))

    assert [item.path.name for item in found] == ["game.zip"]


def test_rejects_archive_outside_approved_roots(tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir()
    outside = _zip(tmp_path / "outside.zip", {"game.nes": b"data"})

    with pytest.raises(ValueError, match="outside approved"):
        approved_archive(outside, (media,))


@pytest.mark.parametrize("name", ("../escape.nes", "/escape.nes", "C:/escape.nes"))
def test_rejects_unsafe_zip_member_paths(tmp_path: Path, name: str) -> None:
    archive = _zip(tmp_path / "unsafe.zip", {name: b"data"})

    with pytest.raises(ValueError, match="unsafe archive path"):
        validate_archive(archive)


def test_rejects_zip_symlinks(tmp_path: Path) -> None:
    archive = tmp_path / "link.zip"
    member = zipfile.ZipInfo("game-link")
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr(member, "outside")

    with pytest.raises(ValueError, match="Symbolic links|symbolic links"):
        validate_archive(archive)


def test_windows_archive_requires_manifest(tmp_path: Path) -> None:
    media = tmp_path / "media"
    library = tmp_path / "library" / "games"
    media.mkdir()
    archive = _zip(media / "portable.zip", {"game/game.exe": b"MZ"})

    with pytest.raises(ValueError, match="require pulsearc.toml"):
        install_archive(archive, (media,), library)


def test_installs_manifested_windows_archive_atomically(tmp_path: Path) -> None:
    media = tmp_path / "media"
    library = tmp_path / "library" / "games"
    media.mkdir()
    archive = _zip(
        media / "portable.zip",
        {
            "pulsearc.toml": b'title = "Portable Test"\nplatform = "windows"\n',
            "game/game.exe": b"MZ",
        },
    )

    installed = install_archive(archive, (media,), library)

    assert installed.parent == library
    assert (installed / "pulsearc.toml").is_file()
    assert (installed / "game" / "game.exe").is_file()
