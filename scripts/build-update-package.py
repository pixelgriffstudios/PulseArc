#!/usr/bin/env python3
"""Build a deterministic, checksum-manifested PulseArc update archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
AIROOT = PROJECT / "archiso/airootfs"
MAPPINGS = (
    (PROJECT / "native-ui", Path("usr/share/pulsearc/native-ui")),
    (PROJECT / "src/pulsearc", Path("usr/lib/pulsearc/core/pulsearc")),
    (PROJECT / "config", Path("usr/share/pulsearc/config")),
)
EXACT = (
    (AIROOT / "usr/local/bin/pulsearc-session", Path("usr/local/bin/pulsearc-session")),
    (AIROOT / "usr/local/bin/pulsearc-audio-select", Path("usr/local/bin/pulsearc-audio-select")),
    (AIROOT / "usr/local/sbin/pulsearc-update", Path("usr/local/sbin/pulsearc-update")),
    (AIROOT / "etc/sudoers.d/20-pulsearc-installer", Path("etc/sudoers.d/20-pulsearc-installer")),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload: dict[str, tuple[bytes, int]] = {}
    for source_root, destination_root in MAPPINGS:
        for source in sorted(source_root.rglob("*")):
            if not source.is_file() or "__pycache__" in source.parts or source.suffix == ".pyc":
                continue
            destination = (destination_root / source.relative_to(source_root)).as_posix()
            payload[destination] = (source.read_bytes(), 0o644)
    for source, destination in EXACT:
        mode = 0o440 if destination.as_posix().startswith("etc/sudoers.d/") else 0o755
        payload[destination.as_posix()] = (source.read_bytes(), mode)
    release = json.dumps(
        {"name": "PulseArc Beta", "version": args.version, "channel": "beta"},
        indent=2,
    ).encode("utf-8") + b"\n"
    payload["etc/pulsearc/release.json"] = (release, 0o644)
    manifest = {
        "format": 1,
        "version": args.version,
        "files": [
            {"path": path, "sha256": digest(data), "mode": mode}
            for path, (data, mode) in sorted(payload.items())
        ],
        "delete": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        for path, (data, _mode) in sorted(payload.items()):
            archive.writestr(f"payload/{path}", data)
    checksum_path = args.output.with_name(args.output.name + ".sha256")
    checksum_path.write_text(f"{digest(args.output.read_bytes())}  {args.output.name}\n", encoding="ascii")
    print(args.output)
    print(checksum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
