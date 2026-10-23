"""Full-size login images must remain independent of small palette samples."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import palette
import previews
from controller import Controller


class LoginImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.preview = self.root / "preview.png"
        Image.new("RGB", (160, 90), "red").save(self.preview)
        self.item = {"id": "1", "signature": "one", "type": "scene", "path": str(self.root), "preview": str(self.preview)}

    def video(self):
        video = self.root / "video.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=1920x1080:d=0.2",
                        "-threads", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True, timeout=10)
        return {**self.item, "type": "video", "file": str(video)}

    def test_video_uses_native_frame_and_reuses_its_cache(self):
        item = self.video()
        source = previews.prepare_login_wallpaper(item, self.cache)
        with Image.open(source) as image:
            self.assertEqual(image.size, (1920, 1080))
            self.assertGreater(image.getpixel((50, 50))[2], 240)
        with patch.object(previews.subprocess, "run", side_effect=AssertionError("cache should be reused")):
            self.assertEqual(previews.prepare_login_wallpaper(item, self.cache), source)

    def test_decoder_failure_does_not_poison_the_native_cache(self):
        item = self.video()
        with patch.object(previews.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "ffmpeg")), \
                self.assertLogs(previews.LOG, level="WARNING"):
            fallback = previews.prepare_login_wallpaper(item, self.cache)
        self.assertIsNone(previews.cached_login_wallpaper(item, self.cache))
        source = previews.prepare_login_wallpaper(item, self.cache)
        self.assertNotEqual(source, fallback)
        with Image.open(source) as image:
            self.assertEqual(image.size, (1920, 1080))

    def test_delayed_scene_capture_replaces_thumbnail_without_upscaling(self):
        with patch.object(previews, "scene_image", side_effect=ValueError("requires composition")), \
                self.assertLogs(previews.LOG, level="WARNING"):
            first = previews.prepare_login_wallpaper(self.item, self.cache)
        with Image.open(first) as image:
            self.assertEqual(image.size, (160, 90))
        capture = self.cache / "renders/1-one.png"
        capture.parent.mkdir()
        Image.new("RGB", (3840, 2160), "blue").save(capture)
        second = previews.prepare_login_wallpaper(self.item, self.cache)
        self.assertNotEqual(first, second)
        with Image.open(second) as image:
            self.assertEqual(image.size, (2560, 1440))

    def test_shell_source_uses_full_size_image_and_preserves_colour_sample(self):
        sample, full = self.root / "sample.png", self.root / "full.jpg"
        Image.new("RGB", (384, 216), "blue").save(sample)
        Image.new("RGB", (1920, 1080), "blue").save(full)
        theme = {"poster": str(sample), "scheme": {"colours": {"primary": "112233"}}}
        with patch.object(palette, "STATE", self.root / "wallpaperengine"):
            palette.apply(theme, full)
        target = self.root / "caelestia"
        self.assertEqual((target / "wallpaper/path.txt").read_text(), str(full))
        self.assertEqual((target / "wallpaper/current").resolve(), full)
        self.assertEqual(json.loads((target / "scheme.json").read_text()), theme["scheme"])
        self.assertEqual(theme["poster"], str(sample))


class BackgroundUpgradeTests(unittest.IsolatedAsyncioTestCase):
    def controller(self):
        c = Controller.__new__(Controller)
        c.closing = asyncio.Event()
        c.generation = 1
        c.rendered = "1"
        c.export_greeter = Mock()
        return c

    async def test_old_decode_cannot_overwrite_a_new_wallpaper(self):
        c = self.controller()
        entered, release = threading.Event(), threading.Event()
        def prepare(*_):
            entered.set()
            release.wait(2)
            return "/fixture/old.jpg"
        with patch("controller.previews.prepare_login_wallpaper", side_effect=prepare), \
                patch("controller.palette.apply_wallpaper_source") as publish:
            task = asyncio.create_task(c.update_login_wallpaper({"id":"1","signature":"a","type":"video"}, 1))
            await asyncio.to_thread(entered.wait, 2)
            c.generation, c.rendered = 2, "2"
            release.set()
            await asyncio.wait_for(task, 2)
        publish.assert_not_called()
        c.export_greeter.assert_not_called()

    async def test_capture_arriving_during_initial_preparation_is_still_upgraded(self):
        c = self.controller()
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            capture = cache / "renders/1-a.png"
            calls = 0
            def prepare(*_):
                nonlocal calls
                calls += 1
                if calls == 1:
                    capture.parent.mkdir()
                    capture.touch()
                    return "/fixture/thumbnail.jpg"
                return "/fixture/full.jpg"
            with patch("controller.CACHE", cache), patch("controller.previews.prepare_login_wallpaper", side_effect=prepare), \
                    patch("controller.palette.apply_wallpaper_source") as publish:
                await c.update_login_wallpaper({"id":"1","signature":"a","type":"scene"}, 1)
            self.assertEqual(publish.call_args_list[-1].args, ("/fixture/full.jpg",))
            self.assertEqual(c.export_greeter.call_args_list[-1].args, ("/fixture/full.jpg",))
