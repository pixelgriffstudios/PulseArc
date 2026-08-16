from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "config" / "runtime-lock.json"
MANIFEST = ROOT / "config" / "bundled-cores.toml"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def install_file(source: Path, destination: Path, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(mode)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--rootfs", type=Path, required=True)
    args = parser.parse_args()

    if shutil.which("fsck.erofs") is None:
        raise SystemExit("fsck.erofs is required (install erofs-utils)")

    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    assets = {item["id"]: item for item in lock["assets"]}
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    installed: list[dict[str, str]] = []

    with tempfile.TemporaryDirectory(prefix="pulsearc-cores-") as temporary:
        temp_root = Path(temporary)
        extracted: dict[str, Path] = {}
        for name, core in manifest["core"].items():
            asset_id = core["asset"]
            asset = assets.get(asset_id)
            if asset is None:
                raise SystemExit(f"{name}: unknown locked asset {asset_id}")
            archive = args.cache / asset["filename"]
            if not archive.is_file():
                raise SystemExit(f"{name}: missing runtime archive {archive}")

            if asset_id not in extracted:
                destination = temp_root / asset_id
                destination.mkdir()
                subprocess.run(
                    ["fsck.erofs", f"--extract={destination}", str(archive)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
                extracted[asset_id] = destination

            source = extracted[asset_id] / core["archive_path"]
            if not source.is_file():
                raise SystemExit(f"{name}: archive path is missing: {core['archive_path']}")
            actual = sha256(source)
            if actual != core["sha256"]:
                raise SystemExit(
                    f"{name}: extracted SHA-256 mismatch: expected {core['sha256']}, got {actual}"
                )

            target = args.rootfs / core["target"].lstrip("/")
            install_file(source, target, 0o755)

            # The Arch ``libretro-core-info`` package owns the matching .info
            # metadata files.  Copying the copies bundled beside the cores into
            # the ArchISO overlay makes pacstrap abort on file conflicts.  Only
            # the locked core binaries need to be supplied by this extractor;
            # metadata comes from the distribution package.

            installed.append(
                {
                    "name": name,
                    "package": core["package"],
                    "asset": asset_id,
                    "target": core["target"],
                    "sha256": actual,
                }
            )
            print(f"CORE OK {name}: {core['target']}")

    report = args.rootfs / "usr/share/pulsearc/runtime-matrix/bundled-cores.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(installed, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
