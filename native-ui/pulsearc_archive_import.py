from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


ARCHIVE_SUFFIXES = {".zip", ".7z", ".rar"}
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024 * 1024
MAX_FILES = 10_000
WINDOWS_SUFFIXES = {".exe", ".msi", ".bat", ".cmd"}
DRIVE_PREFIX = re.compile(r"^[a-zA-Z]:")


@dataclass(frozen=True)
class ArchiveItem:
    path: Path
    source: str
    size: int


def _within(path: Path, roots: Iterable[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def approved_archive(path: Path, roots: Iterable[Path]) -> Path:
    candidate = path.resolve()
    if not candidate.is_file() or candidate.is_symlink():
        raise ValueError("archive is not a regular file")
    if not _within(candidate, roots):
        raise ValueError("archive is outside approved media folders")
    if candidate.suffix.casefold() not in ARCHIVE_SUFFIXES:
        raise ValueError("unsupported archive type")
    if candidate.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("archive is larger than the safety limit")
    return candidate


def discover_archives(roots: Iterable[Path], max_depth: int = 5) -> list[ArchiveItem]:
    found: list[ArchiveItem] = []
    for root in roots:
        if not root.is_dir():
            continue
        root = root.resolve()
        for directory, folders, files in os.walk(root, followlinks=False):
            current = Path(directory)
            depth = len(current.relative_to(root).parts)
            folders[:] = [name for name in folders if not (current / name).is_symlink()]
            if depth >= max_depth:
                folders[:] = []
            for name in files:
                path = current / name
                if path.suffix.casefold() not in ARCHIVE_SUFFIXES or path.is_symlink():
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size <= MAX_ARCHIVE_BYTES:
                    found.append(ArchiveItem(path, root.name or str(root), size))
                if len(found) >= 200:
                    return sorted(found, key=lambda item: item.path.name.casefold())
    return sorted(found, key=lambda item: item.path.name.casefold())


def _safe_member(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/").strip()
    value = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or DRIVE_PREFIX.match(normalized):
        raise ValueError(f"unsafe archive path: {name}")
    if any(part in {"", ".", ".."} for part in value.parts):
        raise ValueError(f"unsafe archive path: {name}")
    return value


def _validate_zip(path: Path) -> tuple[int, int]:
    count = 0
    expanded = 0
    with zipfile.ZipFile(path) as package:
        for member in package.infolist():
            _safe_member(member.filename)
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("symbolic links are not allowed in game archives")
            if member.is_dir():
                continue
            count += 1
            expanded += member.file_size
            if count > MAX_FILES or expanded > MAX_EXPANDED_BYTES:
                raise ValueError("archive exceeds extraction safety limits")
    return count, expanded


def _sevenzip_listing(path: Path) -> tuple[int, int]:
    executable = shutil.which("7z") or shutil.which("7zz")
    if not executable:
        raise RuntimeError("7-Zip is not installed")
    result = subprocess.run(
        [executable, "l", "-slt", "--", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise ValueError("archive could not be inspected")
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        if " = " in line:
            key, value = line.split(" = ", 1)
            current[key] = value
    if current:
        records.append(current)
    count = 0
    expanded = 0
    for record in records:
        name = record.get("Path", "")
        if not name or Path(name).resolve() == path.resolve():
            continue
        _safe_member(name)
        attributes = record.get("Attributes", "")
        if attributes.startswith("D"):
            continue
        count += 1
        expanded += int(record.get("Size", "0") or 0)
        if count > MAX_FILES or expanded > MAX_EXPANDED_BYTES:
            raise ValueError("archive exceeds extraction safety limits")
    return count, expanded


def validate_archive(path: Path) -> tuple[int, int]:
    return _validate_zip(path) if path.suffix.casefold() == ".zip" else _sevenzip_listing(path)


def _extract_zip(path: Path, destination: Path) -> None:
    with zipfile.ZipFile(path) as package:
        for member in package.infolist():
            relative = _safe_member(member.filename)
            target = destination.joinpath(*relative.parts)
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)


def extract_archive(path: Path, destination: Path) -> None:
    validate_archive(path)
    destination.mkdir(parents=True, exist_ok=False)
    if path.suffix.casefold() == ".zip":
        _extract_zip(path, destination)
    else:
        executable = shutil.which("7z") or shutil.which("7zz")
        if not executable:
            raise RuntimeError("7-Zip is not installed")
        result = subprocess.run(
            [executable, "x", "-y", "-bd", f"-o{destination}", "--", str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3600,
        )
        if result.returncode != 0:
            raise ValueError("archive extraction failed")
    count = 0
    expanded = 0
    for item in destination.rglob("*"):
        if item.is_symlink() or not _within(item, (destination,)):
            raise ValueError("archive produced an unsafe link")
        if item.is_file():
            count += 1
            expanded += item.stat().st_size
            if count > MAX_FILES or expanded > MAX_EXPANDED_BYTES:
                raise ValueError("extracted data exceeds safety limits")


def install_archive(path: Path, approved_roots: Iterable[Path], library_root: Path) -> Path:
    source = approved_archive(path, approved_roots)
    library_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pulsearc-archive-", dir=library_root.parent) as temporary:
        extracted = Path(temporary) / "content"
        extract_archive(source, extracted)
        manifests = list(extracted.rglob("pulsearc.toml")) + list(extracted.rglob("*.kzi"))
        windows_files = [item for item in extracted.rglob("*") if item.is_file() and item.suffix.casefold() in WINDOWS_SUFFIXES]
        if windows_files and not manifests:
            raise ValueError("Windows game archives require pulsearc.toml or a legacy .kzi manifest")
        slug = re.sub(r"[^a-z0-9]+", "-", source.stem.casefold()).strip("-")[:64] or "imported-game"
        destination = library_root / slug
        serial = 2
        while destination.exists():
            destination = library_root / f"{slug}-{serial}"
            serial += 1
        extracted.replace(destination)
        return destination
