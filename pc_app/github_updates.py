"""User-initiated GitHub Releases updates for Windows and ESP32-S3.

No silent downloads, auto-execution or auto-flashing. Only official repository
release URLs and component-checked SHA-256 manifests are accepted.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

try:
    from .firmware_update import inspect_firmware
except ImportError:
    from firmware_update import inspect_firmware

try:
    from ._release_version import APP_VERSION
except ImportError:
    APP_VERSION = "development"

REPO = "Abstinence6/ESP32S3-8Fan-8ARGB"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_BASE = f"https://github.com/{REPO}/releases/download/"
WINDOWS_ZIP = "FanARGBControl-Windows.zip"
FIRMWARE_ZIP = "ESP32S3-8Fan-8ARGB-firmware.zip"
PACKAGES = {"windows": (WINDOWS_ZIP, "FanARGBControl.exe"),
            "firmware": (FIRMWARE_ZIP, "firmware.bin")}
MAX_ARCHIVE_SIZE = {"windows": 220 * 1024 * 1024,
                    "firmware": 32 * 1024 * 1024}
MAX_EXTRACT_SIZE = {"windows": 180 * 1024 * 1024,
                    "firmware": 18 * 1024 * 1024}
FIRMWARE_FILES = {"firmware.bin", "bootloader.bin", "partitions.bin", "boot_app0.bin"}
FLASH_OFFSETS = {
    "firmware.bin": "0x10000",
    "bootloader.bin": "0x0",
    "partitions.bin": "0x8000",
    "boot_app0.bin": "0xe000",
}
TAG_PATTERN = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int


@dataclass(frozen=True)
class Release:
    tag: str
    page: str
    assets: dict[str, Asset]

    def package(self, component: str) -> Asset:
        try:
            name, _ = PACKAGES[component]
            asset = self.assets[name]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"GitHub Release {self.tag}: немає архіву {component}") from exc
        if asset.size <= 0 or asset.size > MAX_ARCHIVE_SIZE[component]:
            raise ValueError("Розмір архіву GitHub Release неприпустимий")
        expected = f"{RELEASE_BASE}{self.tag}/{name}"
        if asset.url != expected:
            raise ValueError("GitHub повернув неочікувану адресу release asset")
        return asset


def _download_bytes(url: str, limit: int) -> bytes:
    """Only called with a URL already validated against official GitHub hosts."""
    request = Request(url, headers={
        "User-Agent": "FanARGBControl-UpdateChecker",
        "Accept": "application/vnd.github+json" if url == API_URL
                  else "application/octet-stream",
    })
    try:
        with urlopen(request, timeout=20) as response:
            total = bytearray()
            while len(total) <= limit:
                part = response.read(min(1024 * 1024, limit - len(total) + 1))
                if not part:
                    return bytes(total)
                total.extend(part)
    except HTTPError as exc:
        if exc.code == 404 and url == API_URL:
            raise ValueError("На GitHub ще немає опублікованих Releases.") from exc
        raise ValueError(f"GitHub HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ValueError(f"Не вдалося зв'язатися з GitHub: {exc}") from exc
    raise ValueError("GitHub повернув архів, який перевищує допустимий розмір")


def latest_release(fetch=None) -> Release:
    get = fetch or _download_bytes
    data = get(API_URL, 1024 * 1024)
    try:
        info = json.loads(data)
        tag = info["tag_name"]
        if not isinstance(tag, str) or not TAG_PATTERN.fullmatch(tag):
            raise ValueError("Невідома схема версій GitHub Release")
        if info.get("draft") or info.get("prerelease"):
            raise ValueError("Release ще не є стабільним")
        assets: dict[str, Asset] = {}
        for asset in info["assets"]:
            name = asset["name"]
            if name in assets:
                raise ValueError("GitHub Release має дублікати файлів")
            assets[name] = Asset(name, asset["browser_download_url"], asset["size"])
        page = info["html_url"]
        if page != f"https://github.com/{REPO}/releases/tag/{tag}":
            raise ValueError("Неочікуване посилання на GitHub Release")
        release = Release(tag, page, assets)
        # A valid paired release must have both matching component archives.
        release.package("windows")
        release.package("firmware")
        return release
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Некоректна відповідь GitHub Releases API") from exc


def _validate_manifest(raw: bytes, *, component: str) -> dict:
    if len(raw) > 32 * 1024:
        raise ValueError("Маніфест релізу надто великий")
    try:
        manifest = json.loads(raw)
        if not isinstance(manifest, dict) or manifest["schema"] != 1 or \
           manifest["component"] != component:
            raise ValueError("Маніфест не відповідає типу пакета")
        commit = manifest["source_commit"]
        if not isinstance(commit, str) or not COMMIT_PATTERN.fullmatch(commit):
            raise ValueError("Невідома ревізія вихідного коду")
        files = manifest["files"]
        expected = FIRMWARE_FILES if component == "firmware" else {"FanARGBControl.exe"}
        if not isinstance(files, dict) or set(files) != expected:
            raise ValueError("Реліз не містить очікуваних файлів")
        for name, item in files.items():
            if not isinstance(item, dict) or not SHA_PATTERN.fullmatch(item["sha256"]) or \
               type(item["bytes"]) is not int or item["bytes"] < 1:
                raise ValueError(f"Некоректний SHA-256 або розмір {name}")
        if component == "firmware":
            target = manifest["target"]
            if target["board"] != "esp32-s3-devkitc-1" or \
               target["platformio_env"] != "esp32s3" or \
               target["flash_offsets"] != FLASH_OFFSETS:
                raise ValueError("Пакет прошивки несумісний із конфігурацією ESP32-S3")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Пошкоджений маніфест GitHub Release") from exc
    return manifest


def extract_verified_asset(archive: bytes, component: str, destination: str | Path) -> tuple[str, int]:
    """Validate the entire paired package; atomically place only one requested file."""
    if component not in PACKAGES or len(archive) > MAX_ARCHIVE_SIZE[component]:
        raise ValueError("Невірний компонент або розмір архіву")
    output = Path(destination)
    requested = PACKAGES[component][1]
    if output.suffix.lower() != Path(requested).suffix:
        raise ValueError("Невірний тип файла для збереження")
    if not output.parent.is_dir():
        raise ValueError("Каталог для завантаження не існує")
    if output.exists():
        raise FileExistsError("Такий файл уже існує — вибери інше ім'я")
    try:
        with zipfile.ZipFile(__import__("io").BytesIO(archive)) as bundle:
            items = bundle.infolist()
            names = [i.filename for i in items]
            allowed = (FIRMWARE_FILES | {"manifest.json", "SHA256SUMS", "FLASH.txt"}
                       if component == "firmware" else
                       {"FanARGBControl.exe", "manifest.json", "SHA256SUMS"})
            if len(names) != len(set(names)) or set(names) - allowed or \
               not {"manifest.json", "SHA256SUMS", requested}.issubset(set(names)):
                raise ValueError("Неочікуваний вміст GitHub Release ZIP")
            if any(i.is_dir() or i.filename.startswith("/") or
                   "/" in i.filename or "\\" in i.filename or
                   i.file_size > MAX_EXTRACT_SIZE[component] or
                   (i.external_attr >> 16) & 0o170000 == 0o120000 for i in items):
                raise ValueError("Небезпечний шлях або розмір у ZIP")
            if sum(i.file_size for i in items) > MAX_EXTRACT_SIZE[component]:
                raise ValueError("Розпакований архів надто великий")
            manifest = _validate_manifest(bundle.read("manifest.json"), component=component)
            checksum_lines = "".join(
                f"{info['sha256']}  {name}\n"
                for name, info in sorted(manifest["files"].items())
            )
            if bundle.read("SHA256SUMS") != checksum_lines.encode("ascii"):
                raise ValueError("Файл SHA256SUMS не відповідає маніфесту")
            with tempfile.TemporaryDirectory(prefix=".fanargb-", dir=output.parent) as temp_dir:
                staging = Path(temp_dir) / requested
                for name, info in manifest["files"].items():
                    digest = hashlib.sha256()
                    count = 0
                    with bundle.open(name) as input_file:
                        target = staging.open("wb") if name == requested else None
                        try:
                            while part := input_file.read(1024 * 1024):
                                count += len(part)
                                if count > info["bytes"] or count > MAX_EXTRACT_SIZE[component]:
                                    raise ValueError("Невірна довжина файла в архіві")
                                digest.update(part)
                                if target is not None:
                                    target.write(part)
                        finally:
                            if target is not None:
                                target.close()
                    if count != info["bytes"] or digest.hexdigest() != info["sha256"]:
                        raise ValueError(f"Контрольна сума {name} не збігається")
                if component == "firmware":
                    actual, size = inspect_firmware(str(staging))
                    if actual != manifest["files"][requested]["sha256"] or \
                       size != manifest["files"][requested]["bytes"]:
                        raise ValueError("Файл ESP32-S3 не пройшов перевірку образу")
                os.replace(staging, output)
                return manifest["files"][requested]["sha256"], manifest["files"][requested]["bytes"]
    except (zipfile.BadZipFile, EOFError, OSError) as exc:
        raise ValueError(f"Пошкоджений пакет GitHub Release: {exc}") from exc


def download_release(release: Release, component: str, destination: str | Path, fetch=None) -> tuple[str, int]:
    asset = release.package(component)
    get = fetch or _download_bytes
    blob = get(asset.url, MAX_ARCHIVE_SIZE[component])
    if len(blob) != asset.size:
        raise ValueError("Завантаження GitHub Release неповне або змінене")
    return extract_verified_asset(blob, component, destination)
