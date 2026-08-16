from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .scanner import LibraryEntry, scan, write_index


SUPPORTED_FILESYSTEMS = {"vfat", "exfat", "ntfs", "ext4", "btrfs", "xfs", "f2fs", "iso9660", "udf"}
LABEL_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class BlockVolume:
    path: str
    filesystem: str
    label: str
    uuid: str
    transport: str
    removable: bool
    mountpoint: str | None


def parse_lsblk(document: dict) -> list[BlockVolume]:
    volumes: list[BlockVolume] = []

    def visit(node: dict, inherited_transport: str = "", inherited_removable: bool = False) -> None:
        transport = str(node.get("tran") or inherited_transport or "")
        removable = bool(node.get("rm", inherited_removable))
        filesystem = str(node.get("fstype") or "").lower()
        path = str(node.get("path") or node.get("name") or "")
        mountpoints = node.get("mountpoints") or []
        mountpoint = next((str(item) for item in mountpoints if item), None)
        external = removable or transport in {"usb", "mmc"}
        if external and filesystem in SUPPORTED_FILESYSTEMS and path:
            volumes.append(BlockVolume(
                path=path,
                filesystem=filesystem,
                label=str(node.get("label") or ""),
                uuid=str(node.get("uuid") or ""),
                transport=transport,
                removable=removable,
                mountpoint=mountpoint,
            ))
        for child in node.get("children") or []:
            visit(child, transport, removable)

    for device in document.get("blockdevices") or []:
        visit(device)
    return volumes


def lsblk_volumes() -> list[BlockVolume]:
    process = subprocess.run(
        ["lsblk", "--json", "--paths", "--output", "NAME,PATH,TYPE,FSTYPE,LABEL,UUID,TRAN,RM,MOUNTPOINTS"],
        check=True, capture_output=True, text=True,
    )
    return parse_lsblk(json.loads(process.stdout))


def mount_name(volume: BlockVolume) -> str:
    raw = volume.label or volume.uuid or Path(volume.path).name
    return LABEL_SAFE.sub("_", raw).strip("._")[:64] or "media"


def mount_volume(volume: BlockVolume, root: Path) -> Path | None:
    if volume.mountpoint:
        return Path(volume.mountpoint)
    target = root / mount_name(volume)
    target.mkdir(parents=True, exist_ok=True)
    options = ["nosuid", "nodev", "noexec"]
    if volume.filesystem in {"iso9660", "udf"}:
        options.append("ro")
    elif volume.filesystem in {"vfat", "exfat", "ntfs"}:
        options.extend(["uid=1000", "gid=1000", "umask=0022"])
    result = subprocess.run(
        ["mount", "-t", volume.filesystem, "-o", ",".join(options), volume.path, str(target)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        target.rmdir()
        return None
    return target


def rebuild_library(mounts: list[Path], destination: Path) -> None:
    entries: dict[str, LibraryEntry] = {}
    internal = Path("/var/lib/pulsearc/library")
    roots = ([internal] if internal.is_dir() else []) + mounts
    for root in roots:
        try:
            found = scan(root)
        except OSError:
            continue
        for entry in found:
            entries.setdefault(entry.content_id, entry)
    write_index(list(entries.values()), destination)


def internal_library_signature(root: Path) -> tuple[tuple[str, int, int], ...]:
    """Track directory changes without hashing large installed game files."""
    if not root.is_dir():
        return ()
    signature: list[tuple[str, int, int]] = []
    for directory, child_directories, files in os.walk(root):
        path = Path(directory)
        try:
            modified = path.stat().st_mtime_ns
        except OSError:
            continue
        signature.append((str(path.relative_to(root)), modified, len(child_directories) + len(files)))
    return tuple(signature)


def run() -> None:
    mount_root = Path("/run/media/gamer")
    mount_root.mkdir(parents=True, exist_ok=True)
    os.chown(mount_root, 1000, 1000)
    previous_signature: tuple[object, ...] = ()
    internal = Path("/var/lib/pulsearc/library")
    while True:
        try:
            volumes = lsblk_volumes()
            volume_signature = tuple(sorted((item.path, item.uuid, item.mountpoint or "") for item in volumes))
            signature = (volume_signature, internal_library_signature(internal))
            if signature != previous_signature:
                mounted = [
                    (item, path)
                    for item in volumes
                    if (path := mount_volume(item, mount_root)) is not None
                ]
                # Optical discs are handled by the dedicated PlayStation/DVD
                # detector in the shell.  Walking every file on an ISO9660 or
                # UDF disc made detection slow and exposed game executables,
                # audio tracks and VOB files as separate library entries.
                generic_mounts = [
                    path for item, path in mounted
                    if item.filesystem not in {"iso9660", "udf"}
                ]
                rebuild_library(generic_mounts, Path("/run/pulsearc/library.json"))
                previous_signature = signature
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            Path("/run/pulsearc").mkdir(parents=True, exist_ok=True)
            Path("/run/pulsearc/media-error.txt").write_text(str(exc), encoding="utf-8")
        time.sleep(2.0)


if __name__ == "__main__":
    run()
