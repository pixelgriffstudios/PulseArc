"""Transactional, allow-listed PulseArc system updates.

Update archives contain a ``manifest.json`` and a ``payload/`` tree.  The
manifest lists every installed file and its SHA-256 digest.  Updates never
write user data, games, saves, firmware, network configuration, or profiles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


REPOSITORY = "pixelgriffstudios/PulseArc"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASE_FILE = Path("etc/pulsearc/release.json")
STATE_DIR = Path("var/lib/pulsearc")
ALLOWED_PREFIXES = (
    "usr/share/pulsearc/",
    "usr/lib/pulsearc/",
    "usr/local/bin/pulsearc-",
    "usr/local/sbin/pulsearc-",
    "etc/pulsearc/",
    "etc/systemd/system/pulsearc-",
    "etc/sudoers.d/20-pulsearc-",
)
PROTECTED_PREFIXES = (
    "var/lib/pulsearc/",
    "home/",
    "etc/NetworkManager/",
    "etc/ssh/",
)


class UpdateError(RuntimeError):
    """An update was rejected or could not be applied safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _clean_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise UpdateError(f"unsafe payload path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise UpdateError(f"unsafe payload path: {value!r}")
    cleaned = path.as_posix()
    if cleaned.startswith(PROTECTED_PREFIXES):
        raise UpdateError(f"protected payload path: {cleaned}")
    if not cleaned.startswith(ALLOWED_PREFIXES):
        raise UpdateError(f"payload path is outside the update allow-list: {cleaned}")
    return cleaned


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        raw = archive.read("manifest.json")
    except KeyError as exc:
        raise UpdateError("update archive has no manifest.json") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("update manifest is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != 1:
        raise UpdateError("unsupported update manifest format")
    if not isinstance(manifest.get("version"), str) or not manifest["version"].strip():
        raise UpdateError("update manifest has no version")
    if not isinstance(manifest.get("files"), list) or not isinstance(manifest.get("delete", []), list):
        raise UpdateError("update manifest file lists are invalid")
    return manifest


def _validate_members(archive: zipfile.ZipFile) -> None:
    for info in archive.infolist():
        name = info.filename
        if "\x00" in name or "\\" in name:
            raise UpdateError(f"unsafe archive member: {name!r}")
        path = PurePosixPath(name)
        if path.is_absolute() or any(part == ".." for part in path.parts):
            raise UpdateError(f"unsafe archive member: {name!r}")
        file_type = (info.external_attr >> 16) & 0o170000
        if file_type == stat.S_IFLNK or file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise UpdateError(f"unsupported archive member type: {name!r}")


def _safe_target(root: Path, relative: str) -> Path:
    target = root.joinpath(*PurePosixPath(relative).parts)
    resolved_root = root.resolve()
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    if parent.resolve() != resolved_root and resolved_root not in parent.resolve().parents:
        raise UpdateError(f"payload path escapes target root: {relative}")
    return target


def apply_archive(archive_path: Path, root: Path = Path("/")) -> dict[str, Any]:
    """Validate and atomically apply an update archive below *root*."""
    root = root.resolve()
    state = root / STATE_DIR
    state.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        _validate_members(archive)
        manifest = _read_manifest(archive)
        files: list[tuple[str, str, int]] = []
        seen: set[str] = set()
        for record in manifest["files"]:
            if not isinstance(record, dict):
                raise UpdateError("invalid file record")
            relative = _clean_relative_path(record.get("path", ""))
            expected = str(record.get("sha256", "")).lower()
            if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
                raise UpdateError(f"invalid checksum for {relative}")
            if relative in seen:
                raise UpdateError(f"duplicate payload path: {relative}")
            seen.add(relative)
            mode = int(record.get("mode", 0o644)) & 0o777
            files.append((relative, expected, mode))
        deletions = [_clean_relative_path(value) for value in manifest.get("delete", [])]
        if seen.intersection(deletions):
            raise UpdateError("manifest both installs and deletes the same path")

        stage = Path(tempfile.mkdtemp(prefix="update-stage-", dir=state))
        backup = Path(tempfile.mkdtemp(prefix="update-rollback-", dir=state))
        created: list[Path] = []
        replaced: list[tuple[Path, Path]] = []
        deleted: list[tuple[Path, Path]] = []
        try:
            for relative, expected, mode in files:
                member = f"payload/{relative}"
                try:
                    info = archive.getinfo(member)
                except KeyError as exc:
                    raise UpdateError(f"missing payload file: {relative}") from exc
                if info.is_dir():
                    raise UpdateError(f"payload file is a directory: {relative}")
                staged = stage.joinpath(*PurePosixPath(relative).parts)
                staged.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, staged.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
                if _sha256(staged) != expected:
                    raise UpdateError(f"checksum mismatch: {relative}")
                os.chmod(staged, mode)

            for relative, _expected, _mode in files:
                target = _safe_target(root, relative)
                if target.is_symlink():
                    raise UpdateError(f"refusing to replace symlink: {relative}")
                if target.exists():
                    saved = backup.joinpath(*PurePosixPath(relative).parts)
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, saved)
                    replaced.append((target, saved))
                else:
                    created.append(target)
                staged = stage.joinpath(*PurePosixPath(relative).parts)
                temporary = target.with_name(f".{target.name}.pulsearc-new")
                shutil.copy2(staged, temporary)
                os.replace(temporary, target)

            for relative in deletions:
                target = _safe_target(root, relative)
                if target.is_symlink():
                    raise UpdateError(f"refusing to delete symlink: {relative}")
                if target.exists():
                    saved = backup.joinpath(*PurePosixPath(relative).parts)
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(target, saved)
                    deleted.append((target, saved))

            receipt = {
                "version": manifest["version"],
                "installed_files": len(files),
                "deleted_files": len(deletions),
            }
            (state / "last-update.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            shutil.rmtree(stage, ignore_errors=True)
            shutil.rmtree(backup, ignore_errors=True)
            return receipt
        except Exception:
            for target in reversed(created):
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
            for target, saved in reversed(replaced):
                if saved.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(saved, target)
            for target, saved in reversed(deleted):
                if saved.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(saved, target)
            shutil.rmtree(stage, ignore_errors=True)
            shutil.rmtree(backup, ignore_errors=True)
            raise


def current_version(root: Path = Path("/")) -> str:
    try:
        value = json.loads((root / RELEASE_FILE).read_text(encoding="utf-8"))
        return str(value.get("version", "0.0.0"))
    except (OSError, json.JSONDecodeError, AttributeError):
        return "0.0.0"


def latest_release(timeout: float = 10.0) -> dict[str, Any]:
    request = urllib.request.Request(LATEST_RELEASE_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "PulseArc-Updater"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        release = json.load(response)
    assets = release.get("assets", [])
    update = next((item for item in assets if str(item.get("name", "")).endswith(".update.zip")), None)
    checksum = next((item for item in assets if str(item.get("name", "")).endswith(".update.zip.sha256")), None)
    return {
        "version": str(release.get("tag_name", "")).lstrip("v"),
        "update_url": str((update or {}).get("browser_download_url", "")),
        "checksum_url": str((checksum or {}).get("browser_download_url", "")),
    }


def download_and_apply(root: Path = Path("/")) -> dict[str, Any]:
    release = latest_release()
    if not release["update_url"] or not release["checksum_url"]:
        raise UpdateError("latest release has no signed update assets")
    with tempfile.TemporaryDirectory(prefix="pulsearc-download-") as temporary:
        archive = Path(temporary) / "update.zip"
        checksum = Path(temporary) / "update.sha256"
        urllib.request.urlretrieve(release["update_url"], archive)
        urllib.request.urlretrieve(release["checksum_url"], checksum)
        expected = checksum.read_text(encoding="ascii").split()[0].lower()
        if len(expected) != 64 or _sha256(archive) != expected:
            raise UpdateError("downloaded update checksum does not match")
        return apply_archive(archive, root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.check:
            release = latest_release()
            release["current_version"] = current_version()
            release["available"] = bool(release["update_url"] and release["version"] != release["current_version"])
            print(json.dumps(release))
        elif args.archive:
            if os.geteuid() != 0:
                raise UpdateError("applying an update requires root")
            print(json.dumps(apply_archive(args.archive)))
        elif args.apply:
            if os.geteuid() != 0:
                raise UpdateError("applying an update requires root")
            print(json.dumps(download_and_apply()))
        else:
            parser.error("choose --check, --apply, or --archive")
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
