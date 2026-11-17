"""Github Releases updater uses strict paired assets, integrity and manual install."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from pc_app.github_updates import (
    REPO, API_URL, FIRMWARE_ZIP, WINDOWS_ZIP, RELEASE_BASE,
    Release, Asset, latest_release, extract_verified_asset,
    download_release,
)


def fake_release(version="v1.2.3"):
    page = f"https://github.com/{REPO}/releases/tag/{version}"
    assets = [
        {
            "name": name,
            "browser_download_url": f"{RELEASE_BASE}{version}/{name}",
            "size": 3333,
        }
        for name in (WINDOWS_ZIP, FIRMWARE_ZIP)
    ]
    return json.dumps({
        "tag_name": version, "html_url": page, "assets": assets,
        "draft": False, "prerelease": False,
    }).encode()


def make_bundle(content, *, component="windows", corrupt=False, traversal=False):
    name = "FanARGBControl.exe"
    if component == "firmware":
        raise NotImplementedError("Use fixture-driven ESP tests for actual firmware")
    checksum = hashlib.sha256(content).hexdigest()
    manifest = {
        "schema": 1, "component": component,
        "source_commit": "a" * 40,
        "files": {name: {"sha256": checksum, "bytes": len(content)}},
    }
    sums = f"{checksum}  {name}\n".encode()
    if corrupt:
        sums = b"f" * 64 + f"  {name}\n".encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, content)
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("SHA256SUMS", sums)
        if traversal:
            z.writestr("../malicious.exe", b"bad")
    return stream.getvalue()


class GithubUpdateTests(unittest.TestCase):
    def test_discovery_only_exact_stable_project_release(self):
        release = latest_release(fetch=lambda *_: fake_release())
        self.assertEqual(release.tag, "v1.2.3")
        self.assertEqual(release.package("firmware").name, FIRMWARE_ZIP)
        for version in ("latest", "v1.2.3/../../invalid", "v1.2.3-"):
            with self.assertRaises(ValueError):
                latest_release(fetch=lambda *_, v=version: fake_release(v))
        data = json.loads(fake_release())
        data["assets"][0]["browser_download_url"] = "https://evil.invalid/firmware.zip"
        with self.assertRaises(ValueError):
            latest_release(fetch=lambda *_: json.dumps(data).encode())

    def test_verified_exe_download_is_only_saved_not_executed(self):
        content = b"MZ" + bytes(range(128))
        archive = make_bundle(content)
        source = fake_release()
        release = latest_release(fetch=lambda *_: source)
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "new-FanARGBControl.exe"
            patched = Release(
                release.tag, release.page,
                {
                    **release.assets,
                    WINDOWS_ZIP: Asset(WINDOWS_ZIP, release.package("windows").url, len(archive))
                },
            )
            digest, count = download_release(
                patched, "windows", dest, fetch=lambda *_: archive
            )
            self.assertEqual(digest, hashlib.sha256(content).hexdigest())
            self.assertEqual(count, len(content))
            self.assertEqual(dest.read_bytes(), content)
            with self.assertRaises(FileExistsError):
                extract_verified_asset(archive, "windows", dest)

    def test_hash_and_zip_traversal_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "app.exe"
            for corrupt, traversal in ((True, False), (False, True)):
                with self.assertRaises(ValueError):
                    extract_verified_asset(
                        make_bundle(b"MZ" + bytes(20), corrupt=corrupt, traversal=traversal),
                        "windows", dest,
                    )
                self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
