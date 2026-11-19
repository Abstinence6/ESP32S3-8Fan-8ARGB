"""Create one contiguous ESP32-S3 flash image, written at address 0x0.

Do not replace this operation with concatenation: bootloader, partition,
boot_app0 and app have fixed flash offsets. Gaps are padded with erased
flash bytes (0xFF), which ALSO erases old NVS on write_flash 0x0.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path

FLASH_PARTS = (
    ("bootloader.bin", 0x0000),
    ("partitions.bin", 0x8000),
    ("boot_app0.bin", 0xE000),
    ("firmware.bin", 0x10000),
)
MAX_FLASH_SIZE = 16 * 1024 * 1024

def merge_images(directory: str | Path, output: str | Path) -> dict:
    base = Path(directory)
    out = Path(output)
    parts=[]
    for index,(name,offset) in enumerate(FLASH_PARTS):
        raw=(base / name).read_bytes()
        if not raw:
            raise ValueError("Empty flash image: "+name)
        if name in ("bootloader.bin","firmware.bin") and raw[0] != 0xE9:
            raise ValueError("Invalid ESP32 image magic: "+name)
        if name == "partitions.bin" and raw[:2] != b"\xAA\x50":
            raise ValueError("Invalid ESP32 partition table magic")
        limit = FLASH_PARTS[index+1][1] if index+1<len(FLASH_PARTS) else MAX_FLASH_SIZE
        if offset+len(raw)>limit:
            raise ValueError("Flash image overlaps the next partition or exceeds 16 MB: "+name)
        parts.append((name,offset,raw))
    end=parts[-1][1]+len(parts[-1][2])
    image=bytearray(b"\xFF"*end)
    for name,start,raw in parts:
        image[start:start+len(raw)]=raw
        if image[start:start+len(raw)]!=raw:
            raise AssertionError("Merged image verification failed: "+name)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_bytes(image)
    data=out.read_bytes()
    if data!=image:
        raise IOError("Merged BIN changed after writing")
    return {"size":len(data),"sha256":hashlib.sha256(data).hexdigest()}

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    info=merge_images(args.directory,args.output)
    print(f"Merged 16MB-addressed ESP32-S3 image: {info['size']} bytes, SHA256={info['sha256']}")
    print("WARNING: flashing contiguous image at 0x0 overwrites NVS at 0x9000.")

if __name__=="__main__":
    main()
