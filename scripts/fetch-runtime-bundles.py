from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "config" / "runtime-lock.json"
DEFAULT_CACHE = Path(os.environ.get("PULSEARC_RUNTIME_CACHE", Path.home() / "AppData" / "Local" / "PulseArc" / "RuntimeCache"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    for attempt in range(1, 7):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "PulseArc-Builder/0.0.1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                resumed = offset > 0 and response.status == 206
                if not resumed:
                    offset = 0
                remaining = int(response.headers.get("Content-Length", 0))
                total = offset + remaining if remaining else 0
                mode = "ab" if resumed else "wb"
                with partial.open(mode) as output:
                    copied = offset
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        output.write(block)
                        copied += len(block)
                        if total:
                            print(f"  {copied * 100 // total:3d}%", end="\r", flush=True)
            if total and partial.stat().st_size != total:
                raise OSError(
                    f"incomplete download: expected {total} bytes, got {partial.stat().st_size}"
                )
            partial.replace(destination)
            print("  100%")
            return
        except (ConnectionError, TimeoutError, OSError, urllib.error.URLError) as exc:
            if attempt == 6:
                raise
            print(f"  download interrupted ({exc}); resuming, attempt {attempt + 1}/6")
            time.sleep(2 * attempt)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--write-hashes", action="store_true")
    args = parser.parse_args()
    document = json.loads(LOCK.read_text(encoding="utf-8"))
    changed = False
    for asset in document["assets"]:
        destination = args.cache / asset["filename"]
        print(f"{asset['id']} {asset['version']}")
        if not destination.exists():
            download(asset["url"], destination)
        actual = sha256(destination)
        expected = str(asset.get("sha256", ""))
        if expected and actual != expected:
            print(f"SHA-256 mismatch for {destination}", file=sys.stderr)
            return 2
        if not expected:
            if not args.write_hashes:
                print("Lock is missing SHA-256; run once with --write-hashes", file=sys.stderr)
                return 3
            asset["sha256"] = actual
            changed = True
        print(f"  sha256 {actual}")
    if changed:
        LOCK.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
