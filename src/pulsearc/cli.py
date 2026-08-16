from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from .media import detect, stable_content_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe a game or media file")
    parser.add_argument("path")
    args = parser.parse_args()
    result = asdict(detect(args.path))
    result["content_id"] = stable_content_id(args.path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

