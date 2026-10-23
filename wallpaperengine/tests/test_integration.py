"""Focused regressions for Steam metadata, palette quality and safe recovery."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, AsyncMock, Mock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import catalog
import palette
from controller import Controller, startup_catalog
from PIL import Image


class CatalogTests(unittest.TestCase):
    def test_extra_library_declared_preview_and_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            home = base / "home"
            steam = home / ".local/share/Steam"
            (steam / "steamapps").mkdir(parents=True)
            library = base / "Extra Library"
            (steam / "steamapps/libraryfolders.vdf").write_text('"libraryfolders" { "1" { "path" "' + str(library) + '" } }')
            root = library / "steamapps/workshop/content/431960"
            item = root / "123"
            item.mkdir(parents=True)
            (item / "film.mp4").write_bytes(b"video")
            (item / "art.webp").write_bytes(b"preview")
            (item / "project.json").write_text(json.dumps({"title": "A scene; $(nothing)", "type": "Video", "file": "film.mp4", "preview": "art.webp"}))
            bad = root / "124"
            bad.mkdir()
            (bad / "project.json").write_text(json.dumps({"type": "video", "file": "../123/film.mp4"}))
            with patch.multiple(catalog, HOME=home, CONFIG=base / "config", CACHE=base / "cache"):
                result = catalog.scan()
            good = next(i for i in result["items"] if i["id"] == "123")
            self.assertEqual(good["type"], "video")
            self.assertTrue(good["preview"].endswith("art.webp"))
            self.assertFalse(good["missing"])
            self.assertTrue(next(i for i in result["items"] if i["id"] == "124")["missing"])


class PaletteTests(unittest.TestCase):
    def test_hues_change_while_dark_mode_and_contrast_stay_consistent(self):
        from materialyoucolor.hct import Hct
        with tempfile.TemporaryDirectory() as tmp:
            accents = set()
            for name, rgb in (("red", (175, 35, 45)), ("blue", (25, 70, 180)), ("green", (25, 150, 75))):
                path = Path(tmp) / (name + ".png")
                Image.new("RGB", (160, 90), rgb).save(path)
                result = palette.generate(path, {}, "test", path)
                colours = result["scheme"]["colours"]
                self.assertEqual(result["scheme"]["mode"], "dark")
                self.assertGreaterEqual(palette.contrast(colours["onSurface"], colours["surface"]), 4.5)
                self.assertGreaterEqual(palette.contrast(colours["onPrimary"], colours["primary"]), 4.5)
                expected = Hct.from_int(int("ff" + "".join(f"{v:02x}" for v in rgb), 16))
                actual = Hct.from_int(int("ff" + colours["primary"], 16))
                diff = abs(expected.hue - actual.hue)
                self.assertLess(min(diff, 360-diff), 25)
                accents.add(colours["primary"])
            self.assertEqual(len(accents), 3)

    def test_achromatic_image_does_not_acquire_arbitrary_saturated_accent(self):
        from materialyoucolor.hct import Hct
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "grey.png"
            Image.new("RGB", (100, 100), (60, 60, 60)).save(path)
            result = palette.generate(path, {}, "test", path)
            primary = result["scheme"]["colours"]["primary"]
            self.assertLess(Hct.from_int(int("ff" + primary, 16)).chroma, 12)

    def test_shell_adapter_does_not_invoke_global_theme_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(palette, "STATE", Path(tmp) / "wallpaperengine"), patch("subprocess.run") as run:
                image = Path(tmp) / "poster.png"
                Image.new("RGB", (40, 30), "red").save(image)
                result = palette.generate(image, {}, "test", image)
                palette.apply(result)
                self.assertTrue((Path(tmp) / "caelestia/scheme.json").is_file())
                self.assertTrue((Path(tmp) / "caelestia/wallpaper/current").is_symlink())
                run.assert_not_called()

    def test_real_render_supersedes_a_cached_workshop_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preview, render = root / "preview.png", root / "render.png"
            Image.new("RGB", (160, 90), "red").save(preview)
            Image.new("RGB", (160, 90), "blue").save(render)
            item = {"id": "1", "signature": "one", "preview": str(preview), "type": "scene"}
            with patch.object(palette, "CACHE", root / "cache"):
                first = palette.cached_theme(item, 16/9, {})
                second = palette.cached_theme(item, 16/9, {}, rendered=render)
            self.assertNotEqual(first["seed"], second["seed"])
            self.assertEqual(second["source"], "rendered scene capture")


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_boot_waits_for_compositor_and_saved_item_without_committing_fallback(self):
        fallback = {"id": "1", "type": "video", "missing": False}
        saved = {"id": "2", "type": "video", "missing": False}
        empty = {"assets": "", "items": []}
        partial = {"assets": "/steam/assets", "items": [fallback]}
        complete = {"assets": "/steam/assets", "items": [fallback, saved]}
        monitor = [{"name": "HDMI-A-1", "width": 1920, "height": 1080}]
        with patch("controller.scan", side_effect=[empty, partial, complete]) as scan, \
                patch("controller.hypr", side_effect=[RuntimeError("IPC not ready"), monitor, monitor]):
            result, chosen = await startup_catalog("2", interval=0)
        self.assertEqual(chosen["id"], "2")
        self.assertEqual(result, complete)
        self.assertEqual(scan.call_count, 3)

    async def test_boot_falls_back_only_after_grace_period_if_saved_item_was_removed(self):
        fallback = {"id": "1", "type": "video", "missing": False}
        with patch("controller.scan", return_value={"assets": "/steam/assets", "items": [fallback]}), \
                patch("controller.hypr", return_value=[{"width": 1920, "height": 1080}]):
            _, chosen = await startup_catalog("removed", timeout=0)
        self.assertEqual(chosen["id"], "1")

    async def test_boot_failure_is_retryable_when_monitor_or_assets_are_unavailable(self):
        for monitors, assets in (([], "/steam/assets"), ([{"width": 1920, "height": 1080}], "")):
            with self.subTest(monitors=monitors, assets=assets), \
                    patch("controller.scan", return_value={"assets": assets, "items": []}), \
                    patch("controller.hypr", return_value=monitors):
                with self.assertRaisesRegex(RuntimeError, "will retry"):
                    await startup_catalog("2", timeout=0)

    async def test_health_recovers_after_multiple_renderer_exits(self):
        c = Controller.__new__(Controller)
        c.closing = asyncio.Event()
        c.display_signature = None
        c.process = None
        c.busy = False
        c.stable_since = None
        c.recovery_at = 0
        c.recovery_delay = 4
        c.data = {"active": "1"}
        c.item = lambda ident: {"id": ident, "missing": False}
        c.request = Mock()
        ticks = 0
        async def tick(_):
            nonlocal ticks
            ticks += 1
            if ticks == 3:
                c.closing.set()
        with patch("controller.asyncio.sleep", side_effect=tick), \
                patch("controller.hypr", return_value=[]), \
                patch("controller.time", SimpleNamespace(monotonic=Mock(side_effect=[100, 109, 120]))):
            await c.health()
        self.assertEqual(c.request.call_count, 2)
        self.assertEqual(c.recovery_delay, 16)

    async def test_ipc_timeouts_restart_controller_but_logout_exits_cleanly(self):
        for present in (True, False):
            c = Controller.__new__(Controller)
            c.closing = asyncio.Event()
            c.process = None
            c.busy = False
            c.stable_since = None
            c.recovery_at = 0
            c.recovery_delay = 4
            c.data = {}
            c.item = lambda ident: None
            with self.subTest(session_present=present), \
                    patch("controller.asyncio.sleep", new=AsyncMock()), \
                    patch("controller.hypr", side_effect=RuntimeError("IPC timeout")), \
                    patch("controller.session_present", return_value=present):
                if present:
                    with self.assertRaisesRegex(RuntimeError, "restarting"):
                        await c.health()
                    self.assertFalse(c.closing.is_set())
                else:
                    await c.health()
                    self.assertTrue(c.closing.is_set())

    async def test_failed_switch_restores_previous_renderer_without_committing_new_selection(self):
        previous = {"id": "1", "title": "old", "missing": False}
        failing = {"id": "2", "title": "broken", "missing": False, "signature": "none"}
        c = Controller.__new__(Controller)
        c.data = {"active": "1", "compatibility": {}}
        c.catalog = {"items": [previous, failing]}
        c.generation = 1
        c.pending = (failing, False, 1)
        c.wake = asyncio.Event()
        c.wake.set()
        c.process = None
        c.rendered = "1"
        c.busy = True
        c.stop_renderer = AsyncMock()
        c.spawn = AsyncMock(side_effect=[RuntimeError("unsupported shader"), None])
        c.persist = lambda: None
        c.publish = lambda: None
        task = asyncio.create_task(c.worker())
        for _ in range(100):
            if c.spawn.await_count == 2:
                break
            await asyncio.sleep(.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(c.data["active"], "1")
        self.assertEqual(c.spawn.await_args_list[-1].args[0], previous)
        self.assertEqual(c.data["compatibility"]["2"]["state"], "error")


if __name__ == "__main__":
    unittest.main()
