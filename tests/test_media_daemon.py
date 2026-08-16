import tempfile
import unittest
from pathlib import Path

from pulsearc.media_daemon import internal_library_signature, parse_lsblk


class MediaDaemonTests(unittest.TestCase):
    def test_usb_exfat_and_linux_ext4_are_detected(self):
        document = {"blockdevices": [{
            "path": "/dev/sdb", "tran": "usb", "rm": False,
            "children": [
                {"path": "/dev/sdb1", "fstype": "exfat", "uuid": "A", "mountpoints": [None]},
                {"path": "/dev/sdb2", "fstype": "ext4", "uuid": "B", "mountpoints": [None]},
            ],
        }]}
        self.assertEqual([item.filesystem for item in parse_lsblk(document)], ["exfat", "ext4"])

    def test_internal_root_is_not_considered_removable(self):
        document = {"blockdevices": [{
            "path": "/dev/nvme0n1", "tran": "nvme", "rm": False,
            "children": [{"path": "/dev/nvme0n1p1", "fstype": "btrfs", "mountpoints": ["/"]}],
        }]}
        self.assertEqual(parse_lsblk(document), [])

    def test_internal_signature_changes_for_nested_media(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            album = root / "music" / "album"
            album.mkdir(parents=True)
            before = internal_library_signature(root)
            (album / "song.wav").write_bytes(b"wave")
            after = internal_library_signature(root)
            self.assertNotEqual(before, after)
