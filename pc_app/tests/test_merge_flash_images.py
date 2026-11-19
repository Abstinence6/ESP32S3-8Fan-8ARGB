"""Test ordering, exact fixed offsets and dangerous NVS padding."""
import tempfile
import unittest
from pathlib import Path

from scripts.merge_flash_images import FLASH_PARTS, merge_images

class MergedFlashTests(unittest.TestCase):
    def make_images(self,root: Path) -> None:
        for name,_ in FLASH_PARTS:
            if name=="bootloader.bin":
                payload=b"\xE9"+b"B"*127
            elif name=="partitions.bin":
                payload=b"\xAA\x50"+b"P"*62
            elif name=="boot_app0.bin":
                payload=b"OTA"*32
            else:
                payload=b"\xE9"+b"A"*255
            (root/name).write_bytes(payload)

    def test_offsets_and_nvs_wipe_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            self.make_images(root)
            out=root/"merged.bin"
            info=merge_images(root,out)
            blob=out.read_bytes()
            self.assertEqual(info["size"],0x10100)
            for name,offset in FLASH_PARTS:
                payload=(root/name).read_bytes()
                self.assertEqual(blob[offset:offset+len(payload)],payload)
            self.assertEqual(blob[0x9000:0xD000],b"\xFF"*0x4000)
            self.assertEqual(blob[0xD000:0xE000],b"\xFF"*0x1000)
            self.assertEqual(blob[0x10000],0xE9)

    def test_prevent_overlap_and_corrupt_app(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            self.make_images(root)
            (root/"bootloader.bin").write_bytes(b"\xE9"*0x8100)
            with self.assertRaisesRegex(ValueError,"overlaps"):
                merge_images(root,root/"merged.bin")
            self.make_images(root)
            (root/"firmware.bin").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError,"magic"):
                merge_images(root,root/"merged.bin")

if __name__=="__main__":
    unittest.main()
