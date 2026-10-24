"""Local libraries work without Steam and never rewrite the user's images."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog
import previews
from controller import Controller, startup_catalog
from PIL import Image


class LocalFolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / "Pictures with spaces – 壁紙"
        self.folder.mkdir()
        self.config = self.root / "config"
        self.config.mkdir()
        self.cache = self.root / "cache"
        self.settings = self.config / "settings.json"
        self.settings.write_text(json.dumps({"greeter": {"export_directory": "/keep"}, "transition": {"enabled": False}}))
        for name, value in (("CONFIG", self.config), ("CACHE", self.cache)):
            patcher = patch.object(catalog, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(catalog, "libraries", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def image(self, name="Landscape.PNG", color="blue"):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (1920, 1080), color).save(path)
        return path

    def test_add_remove_preserves_settings_and_original_files(self):
        image = self.image()
        original = image.read_bytes()
        catalog.configure_folder(str(self.folder))
        catalog.configure_folder(str(self.folder / "."))
        self.assertEqual(len(catalog.scan()["folders"]), 1)
        settings = json.loads(self.settings.read_text())
        self.assertEqual(settings["greeter"], {"export_directory": "/keep"})
        self.assertFalse(settings["transition"]["enabled"])
        self.assertEqual(len(catalog.scan()["items"]), 1)
        catalog.configure_folder(str(self.folder), remove=True)
        self.assertEqual(catalog.scan()["items"], [])
        self.assertEqual(image.read_bytes(), original)

    def test_nested_duplicate_roots_and_symlinks_cannot_escape_or_loop(self):
        self.image("nested/photo.jpg")
        outside = self.root / "private.png"
        Image.new("RGB", (80, 60)).save(outside)
        (self.folder / "outside.png").symlink_to(outside)
        (self.folder / "loop").symlink_to(self.folder, target_is_directory=True)
        (self.folder / "bad.png").write_text("not an image")
        (self.folder / "video.mp4").touch()
        self.image(".hidden.png")
        catalog.configure_folder(str(self.folder))
        catalog.configure_folder(str(self.folder / "nested"))
        result = catalog.scan()
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["type"], "image")
        self.assertEqual(result["items"][0]["source"], "local")
        self.assertIn(str(self.folder / "nested"), result["watch"])
        self.assertIn(str(self.config), result["watch"])

    def test_replacing_image_keeps_favorite_identity_and_invalidates_preview(self):
        path = self.image()
        catalog.configure_folder(str(self.folder))
        before = catalog.scan()["items"][0]
        poster = previews.prepare(before, self.cache)
        self.assertEqual((poster["previewWidth"], poster["previewHeight"]), (1280, 720))
        self.assertEqual(poster["previewSource"], "local image")
        replacement = self.folder / "replacement.png"
        Image.new("RGB", (2048, 1080), "red").save(replacement)
        replacement.replace(path)
        after = catalog.scan()["items"][0]
        self.assertEqual(before["id"], after["id"])
        self.assertNotEqual(before["signature"], after["signature"])
        self.assertNotEqual(previews.key(before, self.cache)[0], previews.key(after, self.cache)[0])
        path.unlink()
        self.assertEqual(catalog.scan()["items"], [])

    def test_login_still_keeps_original_resolution_and_exif_orientation(self):
        path = self.folder / "Portrait.jpg"
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB", (1920, 1080), "blue").save(path, exif=exif)
        catalog.configure_folder(str(self.folder))
        item = catalog.scan()["items"][0]
        poster = previews.prepare(item, self.cache)
        self.assertEqual((poster["previewWidth"], poster["previewHeight"]), (720, 1280))
        source = previews.prepare_login_wallpaper(item, self.cache)
        with Image.open(source) as image:
            self.assertEqual(image.size, (810, 1440))

    def test_gif_is_indexed_and_poster_uses_its_first_frame(self):
        path = self.folder / "Animated.gif"
        Image.new("RGB", (800, 450), "red").save(path, save_all=True,
            append_images=[Image.new("RGB", (800, 450), "blue")], duration=100, loop=0)
        catalog.configure_folder(str(self.folder))
        item = catalog.scan()["items"][0]
        result = previews.prepare(item, self.cache)
        self.assertEqual(item["file"], str(path))
        with Image.open(result["displayPreview"]) as image:
            self.assertGreater(image.getpixel((10, 10))[0], 240)

    def test_disconnected_folder_is_retained_and_watches_reconnection_parent(self):
        catalog.configure_folder(str(self.folder))
        self.folder.rmdir()
        result = catalog.scan()
        self.assertEqual(result["folders"], [{"path": str(self.folder), "available": False}])
        self.assertIn(str(self.root), result["watch"])
        catalog.configure_folder(str(self.folder), remove=True)
        self.assertEqual(catalog.scan()["folders"], [])

    def test_generated_cache_is_never_imported_as_a_source(self):
        cache = self.folder / "generated-cache"
        cache.mkdir()
        Image.new("RGB", (400, 200)).save(cache / "poster.png")
        self.image()
        catalog.configure_folder(str(self.folder))
        with patch.object(catalog, "CACHE", cache):
            result = catalog.scan()
        self.assertEqual(len(result["items"]), 1)
        self.assertNotIn(str(cache), result["watch"])

    def test_invalid_path_and_broken_settings_do_not_overwrite_preferences(self):
        for path in ("", str(self.root / "missing"), str(self.settings)):
            with self.assertRaises(ValueError):
                catalog.configure_folder(path)
        self.settings.write_text("{broken")
        with self.assertRaisesRegex(ValueError, "preserved"):
            catalog.configure_folder(str(self.folder))
        self.assertEqual(self.settings.read_text(), "{broken")


class LocalControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_local_image_needs_no_steam_or_engine(self):
        item = {"id": "local-one", "source": "local", "type": "image", "missing": False}
        data = {"items": [item], "assets": "", "folders": [{"path": "/pictures"}]}
        with patch("controller.scan", return_value=data), patch("controller.hypr", return_value=[{"width": 1920, "height": 1080}]), patch("controller.shutil.which", return_value=None):
            self.assertEqual(await startup_catalog(item["id"], timeout=0), (data, item))

    async def test_empty_installation_exposes_folder_picker_without_waiting_for_steam(self):
        data = {"items": [], "assets": "", "folders": []}
        with patch("controller.scan", return_value=data), patch("controller.hypr", return_value=[{"width": 1920, "height": 1080}]):
            self.assertEqual(await startup_catalog(None, timeout=0), (data, None))

    async def test_missing_optional_engine_does_not_block_the_folder_picker(self):
        item = {"id": "123", "source": "workshop", "type": "video", "missing": False}
        data = {"items": [item], "assets": "/steam/assets", "folders": []}
        with patch("controller.scan", return_value=data), patch("controller.hypr", return_value=[{"width": 1920, "height": 1080}]), patch("controller.shutil.which", return_value=None):
            self.assertEqual(await startup_catalog(item["id"], timeout=0), (data, None))

    async def test_health_does_not_restart_a_missing_optional_renderer(self):
        c = Controller.__new__(Controller)
        c.closing = asyncio.Event()
        c.display_signature = None
        c.process = None
        c.busy = False
        c.stable_since = None
        c.recovery_at = 0
        c.recovery_delay = 4
        c.data = {"active": "123"}
        c.catalog = {"assets": "/steam/assets"}
        c.item = lambda ident: {"id": ident, "missing": False}
        c.request = Mock()
        ticks = 0
        async def tick(_):
            nonlocal ticks
            ticks += 1
            if ticks == 2:
                c.closing.set()
        with patch("controller.asyncio.sleep", side_effect=tick), patch("controller.hypr", return_value=[]), patch("controller.shutil.which", return_value=None):
            await c.health()
        c.request.assert_not_called()

    async def test_local_switch_reuses_own_daemon_and_passes_filename_as_one_argument(self):
        c = Controller.__new__(Controller)
        c.process = Mock()
        c.process.poll.return_value = None
        c.image_command = AsyncMock()
        item = {"id": "local-one", "file": "/pictures/a ; $(private) 壁紙.png"}
        with patch("controller.shutil.which", return_value="/usr/bin/awww"), patch("controller.subprocess.Popen") as spawn:
            await c.spawn_image(item, [{"name": "DP-1"}, {"name": "HDMI-A-1"}])
        spawn.assert_not_called()
        c.image_command.assert_awaited_once_with("img", "--namespace", "caelestia-central", "--outputs", "DP-1,HDMI-A-1", "--transition-type", "none", "--", item["file"])
        self.assertEqual(c.rendered, item["id"])

    async def test_missing_local_backend_reports_dependency_before_spawning(self):
        c = Controller.__new__(Controller)
        with patch("controller.shutil.which", return_value=None), patch("controller.subprocess.Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "awww"):
                await c.spawn_image({"id": "local-one"}, [])
        spawn.assert_not_called()

    async def test_stopping_renderer_only_terminates_the_owned_process(self):
        c = Controller.__new__(Controller)
        process = c.process = Mock()
        process.poll.side_effect = [None, 0, 0]
        with patch("controller.subprocess.run") as command:
            await c.stop_renderer()
        process.terminate.assert_called_once()
        command.assert_not_called()
        self.assertIsNone(c.process)

    async def test_cancelled_image_client_is_reaped(self):
        c = Controller.__new__(Controller)
        process = Mock()
        process.communicate = AsyncMock(side_effect=asyncio.CancelledError)
        process.wait = AsyncMock()
        with patch("controller.asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            with self.assertRaises(asyncio.CancelledError):
                await c.image_command("query")
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()
