"""Subscription authority, native poster quality, and atomic change delivery."""
import asyncio
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog
import previews
import subscriptions
from controller import Controller
from PIL import Image


def subscription_text(ids):
    entries = ''.join(f'"{n}" {{ "publishedfileid" "{ident}" "disabled_locally" "{disabled}" }}'
                      for n, (ident, disabled) in enumerate(ids))
    return '"subscribedfiles" { "appid" "431960" ' + entries + ' }'


class LibrarySyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.steam = self.base / "Steam"
        self.source = self.steam / "userdata/10/ugc/431960_subscriptions.vdf"
        self.source.parent.mkdir(parents=True)
        self.cache = self.base / "cache"

    def write(self, ids):
        self.source.write_text(subscription_text(ids))

    def test_leftover_downloads_excluded_and_local_disabled_hidden(self):
        self.write([("123", 0), ("124", 1)])
        for ident in ("123", "124", "125"):
            folder = self.steam / "steamapps/workshop/content/431960" / ident
            folder.mkdir(parents=True)
            (folder / "project.json").write_text('{"type":"video","file":"film.mp4"}')
            (folder / "film.mp4").touch()
        with patch.object(catalog, "libraries", return_value=[self.steam]), patch.object(catalog, "CACHE", self.cache):
            result = catalog.scan()
        self.assertEqual([i["id"] for i in result["items"]], ["123"])
        self.assertTrue((self.steam / "steamapps/workshop/content/431960/125/film.mp4").exists())
        self.assertIn(str(self.source), result["watch"])
        self.assertIn(str(self.source.parent), result["watch"])

    def test_empty_list_is_authoritative_then_resubscribe(self):
        self.write([("123", 0)])
        self.assertEqual(subscriptions.subscribed([self.steam], self.cache)[0], {"123"})
        self.write([])
        self.assertEqual(subscriptions.subscribed([self.steam], self.cache)[0], set())
        self.write([("124", 0)])
        self.assertEqual(subscriptions.subscribed([self.steam], self.cache)[0], {"124"})

    def test_truncated_and_temporarily_missing_metadata_keeps_last_complete_list(self):
        self.write([("123", 0)])
        subscriptions.subscribed([self.steam], self.cache)
        for content in ('"subscribedfiles" { "appid" "431960"', '"subscribedfiles" { "appid" "431960 }'):
            self.source.write_text(content)
            self.assertEqual(subscriptions.subscribed([self.steam], self.cache)[0], {"123"})
        self.source.unlink()
        self.assertEqual(subscriptions.subscribed([self.steam], self.cache)[0], {"123"})

    def test_active_account_takes_precedence_over_newer_other_account(self):
        self.write([("123", 0)])
        other = self.steam / "userdata/20/ugc/431960_subscriptions.vdf"
        other.parent.mkdir(parents=True)
        other.write_text(subscription_text([("999", 0)]))
        login = self.steam / "config/loginusers.vdf"
        login.parent.mkdir()
        login.write_text('"users" { "76561197960265738" { "AutoLogin" "1" } }')  # account 10
        self.assertEqual(subscriptions.subscribed([self.steam], self.cache)[0], {"123"})

    def test_unknown_subscription_metadata_preserves_offline_local_support(self):
        self.assertIsNone(subscriptions.subscribed([self.steam], self.cache)[0])


def make_package(path, members):
    def sized(value):
        raw = value.encode()
        return struct.pack("<I", len(raw)) + raw
    header = sized("PKGV0023") + struct.pack("<I", len(members))
    offset, payload = 0, b""
    for name, data in members.items():
        header += sized(name) + struct.pack("<II", offset, len(data))
        payload += data
        offset += len(data)
    path.write_bytes(header + payload)


def png_texture(width, height):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(buf, format="PNG")
    raw = buf.getvalue()
    return (b"TEXV0005\0TEXI0001\0" + struct.pack("<7I", 0, 0, width, height, width, height, 0)
            + b"TEXB0003\0" + struct.pack("<9I", 1, 13, 1, width, height, 0, 0, len(raw), 0)[:-4] + raw)


class PosterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.cache = self.base / "cache"
        self.original = self.base / "preview.png"
        Image.new("RGB", (160, 160), "red").save(self.original)
        self.item = {"id": "123", "signature": "one", "type": "scene", "path": str(self.base), "preview": str(self.original)}

    def test_scene_uses_original_artwork_instead_of_tiny_workshop_thumbnail(self):
        make_package(self.base / "scene.pkg", {
            "scene.json": json.dumps({"objects": [{"image": "models/base.json", "size": "1920 1080"}]}).encode(),
            "models/base.json": b'{"material":"materials/base.json"}',
            "materials/base.json": b'{"passes":[{"textures":["base"]}]}',
            "materials/base.tex": png_texture(1920, 1080)})
        result = previews.prepare(self.item, self.cache)
        self.assertEqual((result["previewWidth"], result["previewHeight"]), (1280, 720))
        self.assertEqual(result["previewSource"], "original scene artwork")
        with Image.open(result["displayPreview"]) as image:
            self.assertGreater(image.getpixel((100, 100))[2], 240)

    def test_capture_supersedes_cached_thumbnail_and_invalidates_qt_image_url(self):
        first = previews.prepare(self.item, self.cache)
        capture = self.cache / "renders/123-one.png"
        capture.parent.mkdir()
        Image.new("RGB", (1920, 1080), "green").save(capture)
        second = previews.prepare(self.item, self.cache)
        self.assertNotEqual(first["displayPreview"], second["displayPreview"])
        self.assertEqual(second["previewSource"], "rendered scene capture")
        self.assertEqual(previews.cached(self.item, self.cache), second)

    def test_missing_original_art_is_not_faked_by_upscaling(self):
        result = previews.prepare(self.item, self.cache)
        self.assertEqual((result["previewWidth"], result["previewHeight"]), (160, 160))

    def test_video_frame_replaces_small_cover_and_is_reused_from_cache(self):
        video = self.base / "video.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=1280x720:d=0.3",
                        "-threads", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True, timeout=10)
        item = {**self.item, "type": "video", "file": str(video)}
        result = previews.prepare(item, self.cache)
        self.assertEqual((result["previewWidth"], result["previewHeight"]), (1280, 720))
        self.assertEqual(result["previewSource"], "video frame")
        with Image.open(result["displayPreview"]) as image:
            self.assertGreater(image.getpixel((100, 100))[2], 240)
        with patch("previews.subprocess.run", side_effect=AssertionError("cached frame must not be decoded again")):
            self.assertEqual(previews.prepare(item, self.cache), result)

    def test_package_rejects_path_escape_and_truncated_ranges(self):
        path = self.base / "bad.pkg"
        make_package(path, {"../escape": b"no"})
        with self.assertRaises(ValueError):
            previews.Package(path)
        make_package(path, {"scene.json": b"0123456789"})
        path.write_bytes(path.read_bytes()[:-5])
        with self.assertRaises(ValueError):
            previews.Package(path).read("scene.json")

    def test_dxt1_texture_decodes_without_starting_renderer(self):
        header = b"TEXV0005\0TEXI0001\0" + struct.pack("<7I", 7, 0, 4, 4, 4, 4, 0)
        header += b"TEXB0002\0" + struct.pack("<7I", 1, 1, 4, 4, 0, 0, 8)
        image = previews.texture(header + struct.pack("<HHI", 0xf800, 0x07e0, 0))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))


class WatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_atomic_steam_metadata_replacement_refreshes_without_poll_or_hover(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            source = folder / "431960_subscriptions.vdf"
            source.write_text(subscription_text([("123", 0)]))
            controller = Controller.__new__(Controller)
            controller.loop = asyncio.get_running_loop()
            controller.catalog = {"watch": [str(folder), str(source)]}
            controller.watch_fd = None
            controller.refresh_timer = None
            changed = asyncio.Event()
            async def refresh():
                self.assertEqual(subscriptions.read(source)["subscribedfiles"]["0"]["publishedfileid"], "124")
                changed.set()
            controller.refresh = refresh
            controller.setup_watch()
            try:
                temp = folder / "next.vdf"
                temp.write_text(subscription_text([("124", 0)]))
                temp.replace(source)
                await asyncio.wait_for(changed.wait(), timeout=3)
            finally:
                if controller.refresh_timer:
                    controller.refresh_timer.cancel()
                controller.loop.remove_reader(controller.watch_fd)
                import os
                os.close(controller.watch_fd)


if __name__ == "__main__":
    unittest.main()
