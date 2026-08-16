#!/usr/bin/env python3
"""Controller-friendly NetworkManager and BlueZ helpers for PulseArc."""

from __future__ import annotations

import re
import subprocess
from typing import Any


SYSTEM_SETTINGS_HELPER = "/usr/local/sbin/pulsearc-system-settings"


def _run(command: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return result.returncode, result.stdout.strip()


def _split_terse(line: str) -> list[str]:
    """Split nmcli terse output while respecting its backslash escapes."""
    values: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            values.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    values.append("".join(current))
    return values


def wifi_networks(rescan: bool = True) -> list[dict[str, Any]]:
    if rescan:
        _run(["/usr/bin/nmcli", "device", "wifi", "rescan"], timeout=8)
    status, output = _run(
        ["/usr/bin/nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
        timeout=12,
    )
    if status:
        return []
    merged: dict[str, dict[str, Any]] = {}
    for line in output.splitlines():
        fields = _split_terse(line)
        if len(fields) < 4:
            continue
        active, ssid, signal, security = fields[:4]
        ssid = ssid.strip()
        if not ssid:
            continue
        try:
            strength = max(0, min(100, int(signal)))
        except ValueError:
            strength = 0
        candidate = {
            "ssid": ssid,
            "signal": strength,
            "security": security.strip() or "OPEN",
            "active": active.strip() == "*",
        }
        previous = merged.get(ssid)
        if previous is None or candidate["active"] or strength > int(previous["signal"]):
            merged[ssid] = candidate
    return sorted(merged.values(), key=lambda item: (not bool(item["active"]), -int(item["signal"]), str(item["ssid"]).casefold()))


def _saved_connections() -> set[str]:
    status, output = _run(["/usr/bin/nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    if status:
        return set()
    values: set[str] = set()
    for line in output.splitlines():
        fields = _split_terse(line)
        if len(fields) >= 2 and fields[1] in {"802-11-wireless", "wifi"}:
            values.add(fields[0])
    return values


def connect_wifi(ssid: str, password: str = "") -> tuple[bool, str]:
    saved = ssid in _saved_connections()
    if saved and password:
        # A failed first attempt can leave NetworkManager with a profile that
        # has no usable secret.  Replace the PSK explicitly before activating
        # it so NetworkManager never needs an interactive secret agent.
        status, output = _run(
            [
                "/usr/bin/nmcli",
                "connection",
                "modify",
                ssid,
                "802-11-wireless-security.key-mgmt",
                "wpa-psk",
                "802-11-wireless-security.psk",
                password,
                "connection.autoconnect",
                "yes",
            ],
            timeout=15,
        )
        if status == 0:
            status, output = _run(["/usr/bin/nmcli", "connection", "up", "id", ssid], timeout=35)
            if status == 0:
                return True, output or "CONNECTED"
        # If the saved profile is malformed, remove only that selected Wi-Fi
        # profile and let NetworkManager create a clean one below.
        _run(["/usr/bin/nmcli", "connection", "delete", "id", ssid], timeout=12)
        saved = False
    if saved:
        status, output = _run(["/usr/bin/nmcli", "connection", "up", "id", ssid], timeout=30)
        if status == 0:
            return True, output or "CONNECTED"
    command = ["/usr/bin/nmcli", "device", "wifi", "connect", ssid]
    if password:
        command.extend(["password", password])
    status, output = _run(command, timeout=40)
    return status == 0, output or ("CONNECTED" if status == 0 else "CONNECTION FAILED")


def disconnect_wifi() -> tuple[bool, str]:
    status, output = _run(["/usr/bin/nmcli", "networking", "connectivity", "check"], timeout=8)
    return status == 0, output


_DEVICE_RE = re.compile(r"^Device\s+([0-9A-Fa-f:]{17})\s+(.+)$")


def _ensure_bluetooth_ready() -> bool:
    status, output = _run(["/usr/bin/systemctl", "is-active", "bluetooth.service"], timeout=3)
    if status == 0 and output.strip() == "active":
        return True
    _run(["/usr/bin/sudo", "-n", SYSTEM_SETTINGS_HELPER, "bluetooth-on"], timeout=12)
    status, output = _run(["/usr/bin/systemctl", "is-active", "bluetooth.service"], timeout=3)
    return status == 0 and output.strip() == "active"


def bluetooth_devices(scan: bool = True) -> list[dict[str, Any]]:
    if not _ensure_bluetooth_ready():
        return []
    _run(["/usr/bin/bluetoothctl", "power", "on"], timeout=8)
    if scan:
        _run(["/usr/bin/bluetoothctl", "--timeout", "5", "scan", "on"], timeout=8)
    status, output = _run(["/usr/bin/bluetoothctl", "devices"], timeout=8)
    if status:
        return []
    devices: list[dict[str, Any]] = []
    for line in output.splitlines():
        match = _DEVICE_RE.match(line.strip())
        if not match:
            continue
        address, name = match.groups()
        _info_status, info = _run(["/usr/bin/bluetoothctl", "info", address], timeout=6)
        paired = "Paired: yes" in info
        connected = "Connected: yes" in info
        trusted = "Trusted: yes" in info
        icon_match = re.search(r"Icon:\s*(\S+)", info)
        devices.append({
            "address": address.upper(),
            "name": name.strip(),
            "paired": paired,
            "connected": connected,
            "trusted": trusted,
            "icon": icon_match.group(1) if icon_match else "device",
        })
    return sorted(devices, key=lambda item: (not bool(item["connected"]), not bool(item["paired"]), str(item["name"]).casefold()))


def pair_or_connect_bluetooth(address: str) -> tuple[bool, str]:
    if not _ensure_bluetooth_ready():
        return False, "BLUETOOTH SERVICE COULD NOT BE STARTED"
    _run(["/usr/bin/bluetoothctl", "power", "on"], timeout=8)
    status, info = _run(["/usr/bin/bluetoothctl", "info", address], timeout=8)
    if status == 0 and "Connected: yes" in info:
        return True, "ALREADY CONNECTED"
    if "Paired: yes" not in info:
        status, output = _run(
            ["/usr/bin/bluetoothctl", "--agent", "NoInputNoOutput", "pair", address],
            timeout=35,
        )
        if status:
            return False, output or "PAIRING FAILED"
    _run(["/usr/bin/bluetoothctl", "trust", address], timeout=10)
    status, output = _run(["/usr/bin/bluetoothctl", "connect", address], timeout=25)
    return status == 0, output or ("CONNECTED" if status == 0 else "CONNECTION FAILED")


def disconnect_bluetooth(address: str) -> tuple[bool, str]:
    status, output = _run(["/usr/bin/bluetoothctl", "disconnect", address], timeout=12)
    return status == 0, output or ("DISCONNECTED" if status == 0 else "DISCONNECT FAILED")
