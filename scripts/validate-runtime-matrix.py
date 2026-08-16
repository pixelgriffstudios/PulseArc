from __future__ import annotations

import argparse
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYSTEMS = ROOT / "config" / "systems.toml"
BUNDLED = ROOT / "config" / "bundled-cores.toml"
PACKAGES = ROOT / "archiso" / "packages.x86_64"


def arch_packages() -> set[str]:
    result: set[str] = set()
    for line in PACKAGES.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if value:
            result.add(value)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rootfs", type=Path)
    args = parser.parse_args()

    document = tomllib.loads(SYSTEMS.read_text(encoding="utf-8"))
    runners = document.get("runners", {})
    systems = document.get("systems", {})
    bundled = tomllib.loads(BUNDLED.read_text(encoding="utf-8")).get("core", {})
    bundled_packages = {entry["package"]: entry for entry in bundled.values()}
    packages = arch_packages()
    failures: list[str] = []

    for system_name, system in systems.items():
        names = [system.get("primary", ""), *system.get("fallbacks", [])]
        for runner_name in names:
            if runner_name not in runners:
                failures.append(f"{system_name}: unknown runner {runner_name}")

    for runner_name, runner in runners.items():
        if runner.get("kind") != "retroarch":
            continue
        arguments = runner.get("arguments", [])
        try:
            core_path = arguments[arguments.index("-L") + 1]
        except (ValueError, IndexError):
            failures.append(f"{runner_name}: RetroArch runner has no -L core path")
            continue
        package = runner.get("package", "")
        if package in packages:
            source = f"Arch package {package}"
        elif package in bundled_packages:
            entry = bundled_packages[package]
            source = f"bundled asset {entry['asset']}"
            if entry["target"] != core_path:
                failures.append(
                    f"{runner_name}: core path {core_path} does not match bundled target {entry['target']}"
                )
            if args.rootfs is not None and not (args.rootfs / core_path.lstrip("/")).is_file():
                failures.append(f"{runner_name}: staged core is missing: {core_path}")
        else:
            failures.append(f"{runner_name}: package has no build source: {package}")
            continue
        print(f"CORE SOURCE OK {runner_name}: {core_path} ({source})")

    if failures:
        for failure in failures:
            print(f"RUNTIME MATRIX ERROR: {failure}")
        return 1
    print(f"RUNTIME MATRIX OK: {len(systems)} systems, {len(runners)} runners")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
