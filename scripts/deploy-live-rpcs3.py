#!/usr/bin/env python3
"""Install RPCS3 plus privately supplied PS3 firmware/keys on a live console."""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import sys
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]
APPIMAGE = ROOT / "vendor/cache/rpcs3-v0.0.42-19729-db907a25_linux64.AppImage"
PUP = Path.home() / "Downloads/PS3UPDAT.PUP"
KEYS = Path.home() / "Downloads/Sony - PlayStation 3 - Keys (4460) (2026-08-09 08-36-13).zip"
DESTINATION = "/home/gamer/.local/share/pulsearc/runners/rpcs3/rpcs3.AppImage"
REGISTRY = "/home/gamer/.config/pulsearc/systems.toml"


def remote(client: paramiko.SSHClient, command: str, timeout: int = 180) -> str:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    output = stdout.read().decode("utf-8", errors="replace")
    error = stderr.read().decode("utf-8", errors="replace")
    status = stdout.channel.recv_exit_status()
    if status:
        raise RuntimeError(f"remote command failed ({status}): {command}\n{output}\n{error}")
    return output + error


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--user", default="gamer")
    args = parser.parse_args()
    password = os.environ.get("PULSEARC_REMOTE_PASSWORD")
    if not password:
        raise SystemExit("PULSEARC_REMOTE_PASSWORD is required")
    for required in (APPIMAGE, PUP, KEYS):
        if not required.is_file():
            raise SystemExit(f"required file is missing: {required}")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        args.host, username=args.user, password=password, allow_agent=False,
        look_for_keys=False, timeout=15, banner_timeout=15, auth_timeout=15,
    )
    try:
        remote(
            client,
            "install -d -m 0755 ~/.cache/pulsearc ~/.config/pulsearc "
            "~/.local/share/pulsearc/runners/rpcs3 ~/.local/share/pulsearc/rpcs3-firmware "
            "~/.local/share/pulsearc/rpcs3-shared ~/.local/share/pulsearc/rpcs3-keys "
            "~/.local/share/pulsearc/core/pulsearc ~/.local/share/pulsearc/native-ui "
            "~/.local/share/pulsearc/rollback",
        )
        stage_app = "/home/gamer/.cache/pulsearc/rpcs3.AppImage.new"
        stage_pup = "/home/gamer/.cache/pulsearc/PS3UPDAT.PUP.new"
        stage_keys = "/home/gamer/.cache/pulsearc/ps3-keys.zip.new"
        files = {
            APPIMAGE: stage_app,
            PUP: stage_pup,
            KEYS: stage_keys,
            ROOT / "src/pulsearc/control.py": "/home/gamer/.local/share/pulsearc/core/pulsearc/control.py.new",
            ROOT / "src/pulsearc/scanner.py": "/home/gamer/.local/share/pulsearc/core/pulsearc/scanner.py.new",
            ROOT / "src/pulsearc/metadata.py": "/home/gamer/.local/share/pulsearc/core/pulsearc/metadata.py.new",
            ROOT / "native-ui/pulsearc_3d_library.py": "/home/gamer/.local/share/pulsearc/native-ui/pulsearc_3d_library.py.new",
        }
        registry = (ROOT / "config/systems.toml").read_text(encoding="utf-8")
        registry = registry.replace(
            'executable = "/usr/local/bin/pulsearc-appimage"\n'
            'arguments = ["duckstation", "-batch", "-fullscreen", "{content}"]',
            'executable = "/home/gamer/.local/share/pulsearc/runners/duckstation/duckstation.AppImage"\n'
            'arguments = ["-batch", "-fullscreen", "{content}"]',
            1,
        )
        registry = registry.replace(
            'executable = "/usr/local/bin/pulsearc-appimage"\n'
            'arguments = ["rpcs3", "--no-gui", "--fullscreen", "--input-config=PulseArc", "{content}"]',
            'executable = "/home/gamer/.local/share/pulsearc/runners/rpcs3/rpcs3.AppImage"\n'
            'arguments = ["--no-gui", "--fullscreen", "--input-config=PulseArc", "{content}"]',
            1,
        )
        if "/home/gamer/.local/share/pulsearc/runners/duckstation/duckstation.AppImage" not in registry:
            raise RuntimeError("failed to preserve the live DuckStation override")
        if "/home/gamer/.local/share/pulsearc/runners/rpcs3/rpcs3.AppImage" not in registry:
            raise RuntimeError("failed to create the live RPCS3 override")
        registry_bytes = registry.encode("utf-8")
        with client.open_sftp() as sftp:
            for source, target in files.items():
                sftp.put(str(source), target)
                sftp.chmod(target, 0o755 if source == APPIMAGE else 0o644)
            with sftp.open(REGISTRY + ".new", "w") as output:
                output.write(registry_bytes)
            sftp.chmod(REGISTRY + ".new", 0o644)
        for source, target in files.items():
            actual = remote(client, f"sha256sum {shlex.quote(target)}").split()[0]
            if actual != digest(source):
                raise RuntimeError(f"checksum mismatch: {target}")
        actual_registry = remote(client, f"sha256sum {REGISTRY}.new").split()[0]
        if actual_registry != hashlib.sha256(registry_bytes).hexdigest():
            raise RuntimeError("checksum mismatch: live systems registry")

        remote(
            client,
            "stamp=$(date +%Y%m%d-%H%M%S); backup=$HOME/.local/share/pulsearc/rollback/$stamp-rpcs3; "
            "mkdir -p \"$backup\"; "
            f"cp -a {DESTINATION} \"$backup/\" 2>/dev/null || true; "
            "cp -a ~/.config/pulsearc/systems.toml \"$backup/\" 2>/dev/null || true; "
            f"mv {stage_app} {DESTINATION}; chmod 0755 {DESTINATION}; "
            f"mv {stage_pup} ~/.local/share/pulsearc/rpcs3-firmware/PS3UPDAT.PUP; "
            f"mv {stage_keys} ~/.cache/pulsearc/ps3-keys.zip; "
            "mv ~/.local/share/pulsearc/core/pulsearc/control.py.new ~/.local/share/pulsearc/core/pulsearc/control.py; "
            "mv ~/.local/share/pulsearc/core/pulsearc/scanner.py.new ~/.local/share/pulsearc/core/pulsearc/scanner.py; "
            "mv ~/.local/share/pulsearc/core/pulsearc/metadata.py.new ~/.local/share/pulsearc/core/pulsearc/metadata.py; "
            "mv ~/.local/share/pulsearc/native-ui/pulsearc_3d_library.py.new ~/.local/share/pulsearc/native-ui/pulsearc_3d_library.py; "
            f"mv {REGISTRY}.new {REGISTRY}; chmod 0644 {REGISTRY}",
        )
        remote(
            client,
            "python - <<'PY'\n"
            "from pathlib import Path\n"
            "import zipfile\n"
            "archive=Path.home()/'.cache/pulsearc/ps3-keys.zip'\n"
            "root=(Path.home()/'.local/share/pulsearc/rpcs3-keys').resolve()\n"
            "root.mkdir(parents=True, exist_ok=True)\n"
            "with zipfile.ZipFile(archive) as source:\n"
            "    for item in source.infolist():\n"
            "        if item.is_dir() or Path(item.filename).suffix.lower() not in {'.key','.dkey'}:\n"
            "            continue\n"
            "        target=(root/Path(item.filename).name).resolve()\n"
            "        if target.parent != root:\n"
            "            raise RuntimeError('unsafe PS3 key path')\n"
            "        target.write_bytes(source.read(item))\n"
            "print('PULSEARC_PS3_KEYS', len(list(root.glob('*.key'))) + len(list(root.glob('*.dkey'))))\n"
            "PY",
        )
        shared = "/home/gamer/.local/share/pulsearc/rpcs3-shared"
        firmware = "/home/gamer/.local/share/pulsearc/rpcs3-firmware/PS3UPDAT.PUP"
        installed_files = int(remote(
            client,
            f"find {shared}/rpcs3/dev_flash -type f 2>/dev/null | wc -l",
        ).strip() or "0")
        if installed_files < 1000:
            try:
                output = remote(
                    client,
                    f"DISPLAY=:0 XAUTHORITY=/home/gamer/.Xauthority APPIMAGE_EXTRACT_AND_RUN=1 "
                    f"XDG_CONFIG_HOME={shared} {DESTINATION} --headless --installfw {firmware}",
                    timeout=600,
                )
                print(output, end="")
            except RuntimeError:
                # Some AppImage builds abort during GUI teardown after firmware
                # reaches 100%.  Accept that exit only when the installed tree
                # independently proves the operation completed.
                installed_files = int(remote(
                    client,
                    f"find {shared}/rpcs3/dev_flash -type f 2>/dev/null | wc -l",
                ).strip() or "0")
                if installed_files < 1000:
                    raise
        print(remote(
            client,
            f"test \"$(sha256sum {DESTINATION} | cut -d' ' -f1)\" = {digest(APPIMAGE)}; "
            f"test -d {shared}/rpcs3/dev_flash; "
            "PYTHONPATH=$HOME/.local/share/pulsearc/core /usr/bin/python -c "
            "'from pathlib import Path; from pulsearc.control import REGISTRY, _prepare_rpcs3_config; "
            "from pulsearc.registry import RuntimeRegistry; r=RuntimeRegistry.load(REGISTRY); "
            "assert r.systems[\"playstation-3\"].primary == \"rpcs3\"; "
            "p=_prepare_rpcs3_config(Path(\"/tmp/pulsearc-rpcs3-test\")); "
            "assert \"Renderer: Vulkan\" in p.read_text(); print(\"PULSEARC_RPCS3_READY\")'",
        ))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
