#!/usr/bin/env python3
"""Build the compact PulseArc offline cover pack from the print label archives."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import zipfile
from pathlib import Path

from PIL import Image


NON_ALNUM = re.compile(r"[^a-z0-9]+")
REGION_TAGS = re.compile(r"\s*[\[(](?:USA|US|Europe|Japan|World|En(?:,[A-Za-z]{2})*|Rev\s*\d+|Disc\s*\d+)[\])]", re.I)
SYSTEMS = {
    "NES": "nes",
    "SNES": "snes",
    "GENESIS": "mega-drive",
    "N64": "nintendo-64",
}
KNOWN_CONTENT_SUFFIXES = {
    ".7z", ".bin", ".chd", ".cue", ".gb", ".gba", ".gbc", ".iso",
    ".md", ".nes", ".rvz", ".sfc", ".smc", ".v64", ".wbfs", ".wux",
    ".z64", ".zip",
}


def title_key(value: str) -> str:
    name = Path(value).name
    suffix = Path(name).suffix.casefold()
    value = (name[:-len(suffix)] if suffix in KNOWN_CONTENT_SUFFIXES else name)
    value = value.replace("_", " ").replace(".", " ")
    value = REGION_TAGS.sub("", value)
    return NON_ALNUM.sub("", " ".join(value.split()).casefold())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Official-USA-Game-Label-Sets directory")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--width", type=int, default=270)
    parser.add_argument("--height", type=int, default=360)
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict[str, str]] = {}
    converted = 0
    for system_key, platform in SYSTEMS.items():
        archive = next(args.source.glob(f"Official-USA-{system_key}-*-Covers-and-Labels.zip"))
        csv_path = next(args.source.glob(f"Official-USA-{system_key}-*-Index.csv"))
        rows = list(csv.DictReader(csv_path.open("r", encoding="utf-8-sig", newline="")))
        system_index: dict[str, str] = {}
        output_dir = args.destination / platform
        output_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as package:
            names = {Path(name).name: name for name in package.namelist() if "Print-Ready-Label-PNGs/" in name}
            for row in rows:
                label_name = str(row.get("label_jpg", "")).strip()
                member = names.get(label_name)
                if not member:
                    continue
                output_name = f"{int(row['label_number']):03d}.png"
                destination = output_dir / output_name
                if not destination.is_file():
                    with Image.open(io.BytesIO(package.read(member))) as image:
                        image.thumbnail((args.width, args.height), Image.Resampling.LANCZOS)
                        image.convert("RGB").save(destination, "PNG", optimize=True)
                relative = destination.relative_to(args.destination).as_posix()
                for title in (row.get("catalog_title", ""), row.get("cover_title", "")):
                    key = title_key(str(title))
                    if key:
                        system_index[key] = relative
                converted += 1
        index[platform] = system_index
    (args.destination / "index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"Built {converted} indexed covers in {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
