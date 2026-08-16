from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from pulsearc.updater import UpdateError, apply_archive


def _update(path: Path, files: dict[str, bytes], *, delete: list[str] | None = None, corrupt: str = "") -> Path:
    records = []
    for name, content in files.items():
        digest = hashlib.sha256(content).hexdigest()
        if name == corrupt:
            digest = "0" * 64
        records.append({"path": name, "sha256": digest, "mode": 0o644})
    manifest = {"format": 1, "version": "0.1.0-test", "files": records, "delete": delete or []}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, content in files.items():
            archive.writestr(f"payload/{name}", content)
    return path


def test_update_applies_only_system_payload_and_preserves_state(tmp_path: Path) -> None:
    state = tmp_path / "var/lib/pulsearc/profiles/default/save.dat"
    state.parent.mkdir(parents=True)
    state.write_bytes(b"save")
    archive = _update(tmp_path / "good.zip", {"usr/share/pulsearc/native-ui/new.py": b"new"})
    result = apply_archive(archive, tmp_path)
    assert result["version"] == "0.1.0-test"
    assert (tmp_path / "usr/share/pulsearc/native-ui/new.py").read_bytes() == b"new"
    assert state.read_bytes() == b"save"


@pytest.mark.parametrize("path", ["../etc/passwd", "/etc/passwd", "home/gamer/.ssh/key", "var/lib/pulsearc/saves/x"])
def test_update_rejects_unsafe_or_protected_paths(tmp_path: Path, path: str) -> None:
    archive = _update(tmp_path / "bad.zip", {path: b"bad"})
    with pytest.raises(UpdateError):
        apply_archive(archive, tmp_path)


def test_update_checksum_failure_leaves_existing_file_unchanged(tmp_path: Path) -> None:
    target = tmp_path / "usr/share/pulsearc/native-ui/ui.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old")
    archive = _update(
        tmp_path / "corrupt.zip",
        {"usr/share/pulsearc/native-ui/ui.py": b"new"},
        corrupt="usr/share/pulsearc/native-ui/ui.py",
    )
    with pytest.raises(UpdateError, match="checksum mismatch"):
        apply_archive(archive, tmp_path)
    assert target.read_bytes() == b"old"


def test_update_rejects_zip_traversal_member(tmp_path: Path) -> None:
    archive = tmp_path / "traversal.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("manifest.json", json.dumps({"format": 1, "version": "x", "files": [], "delete": []}))
        output.writestr("../escape", b"bad")
    with pytest.raises(UpdateError, match="unsafe archive member"):
        apply_archive(archive, tmp_path)
