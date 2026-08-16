from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_FILE = ROOT / "archiso" / "packages.x86_64"


def packages() -> list[str]:
    result = []
    for line in PACKAGE_FILE.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if value:
            result.append(value)
    return result


def exists(package: str) -> bool:
    url = "https://archlinux.org/packages/search/json/?q=" + urllib.parse.quote(package)
    request = urllib.request.Request(url, headers={"User-Agent": "PulseArc-Builder/0.0.1"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                document = json.load(response)
            break
        except (ConnectionError, TimeoutError, urllib.error.URLError):
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))
    return any(item.get("pkgname") == package for item in document.get("results", []))


def main() -> int:
    missing = []
    for package in packages():
        present = exists(package)
        print(f"{'OK' if present else 'MISSING':7} {package}")
        if not present:
            missing.append(package)
        time.sleep(0.08)
    if missing:
        print("Missing exact package names: " + ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
