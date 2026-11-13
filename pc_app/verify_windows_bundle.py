"""Check the actual Windows onefile executable for local Python modules.

This catches builds that pass unit tests but fail at runtime with
"ModuleNotFoundError: No module named 'monitor'" after PyInstaller packaging.

Usage: python pc_app/verify_windows_bundle.py dist/FanARGBControl.exe
"""
from __future__ import annotations

import marshal
from pathlib import Path
import struct
import sys
import zlib

REQUIRED = frozenset({
    "monitor", "sacn_bridge", "protocol", "serial_owner",
    "profiles", "config_presets", "agent", "ui_dashboard", "ui_dashboard_model",
    "nwinfo_sensors", "smart_control", "autostart", "settings_widgets",
    "hardware_sensor_ui", "argb_effects", "argb_studio_ui",
    "config_backup", "maintenance_ui", "firmware_update", "esptool",
    "diagnostics", "diagnostics_ui", "sensor_manager_ui",
})
MAGIC = b"MEI\x0c\x0b\x0a\x0b\x0e"
COOKIE = struct.Struct("!8sIIII64s")
TOC_RECORD = struct.Struct("!IIIIBc")


def bundled_modules(executable: Path) -> set[str]:
    raw = executable.read_bytes()
    cookie_pos = raw.rfind(MAGIC)
    if cookie_pos == -1 or cookie_pos + COOKIE.size > len(raw):
        raise ValueError("Not a PyInstaller CArchive executable")
    marker, package_size, table_offset, table_size, _pyver, _python_lib = (
        COOKIE.unpack_from(raw, cookie_pos)
    )
    if marker != MAGIC:
        raise ValueError("Invalid PyInstaller cookie")
    package_start = cookie_pos + COOKIE.size - package_size
    if package_start < 0 or table_offset + table_size > package_size:
        raise ValueError("Invalid PyInstaller archive offsets")

    index = package_start + table_offset
    toc_end = index + table_size
    while index < toc_end:
        size, offset, compressed_length, _unpacked_length, compression, _tag = (
            TOC_RECORD.unpack_from(raw, index)
        )
        if size < TOC_RECORD.size or index + size > toc_end:
            raise ValueError("Invalid PyInstaller TOC entry")
        name = raw[index + TOC_RECORD.size:index + size].rstrip(b"\x00")
        index += size
        if name != b"PYZ.pyz":
            continue
        content = raw[package_start + offset:package_start + offset + compressed_length]
        if compression:
            content = zlib.decompress(content)
        if not content.startswith(b"PYZ\x00"):
            raise ValueError("Invalid PYZ module archive")
        embedded_toc_at = struct.unpack_from("!i", content, 8)[0]
        pyz_table = marshal.loads(content[embedded_toc_at:])
        if isinstance(pyz_table, dict):
            return set(pyz_table)
        return {name for name, _record in pyz_table}
    raise ValueError("PyInstaller PYZ.pyz not present")


def bundled_files(executable: Path) -> set[str]:
    """Check the PyInstaller CArchive includes a native nwinfo.exe executable."""
    raw = executable.read_bytes()
    cookie_pos = raw.rfind(MAGIC)
    if cookie_pos == -1 or cookie_pos + COOKIE.size > len(raw):
        raise ValueError("Not a PyInstaller CArchive")
    _marker, package_size, table_offset, table_size, _ver, _dll = COOKIE.unpack_from(raw, cookie_pos)
    base = cookie_pos + COOKIE.size - package_size
    pos, end = base + table_offset, base + table_offset + table_size
    found = set()
    while pos < end:
        (size, _offset, _compressed_len, _uncompressed_len,
         _compression, _type) = TOC_RECORD.unpack_from(raw, pos)
        if size < TOC_RECORD.size or pos + size > end:
            raise ValueError("Invalid PyInstaller TOC")
        name = raw[pos + TOC_RECORD.size:pos + size].rstrip(b"\x00")
        found.add(name.decode("utf-8", errors="replace").replace("\\", "/").lower())
        pos += size
    return found


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: verify_windows_bundle.py <path-to-FanARGBControl.exe>", file=sys.stderr)
        return 2
    modules = bundled_modules(Path(sys.argv[1]))
    missing = sorted(REQUIRED - modules)
    if missing:
        print("FAIL: Windows EXE is missing: " + ", ".join(missing), file=sys.stderr)
        return 1
    entries = bundled_files(Path(sys.argv[1]))
    if not any(x.endswith("/nwinfo.exe") or x == "nwinfo.exe" for x in entries):
        print("FAIL: NWinfo sensor engine is missing from Windows EXE", file=sys.stderr)
        return 1
    print("PASS: All project modules and NWinfo sensor executable bundled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
