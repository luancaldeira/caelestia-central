"""First-frame readiness and safe fallback/cancellation of desktop snapshots."""
import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from controller import Controller
import transition


class RendererReadyTests(unittest.IsolatedAsyncioTestCase):
    async def test_mapped_black_video_surface_does_not_trigger_reveal_before_decode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            c = Controller.__new__(Controller)
            c.catalog = {"assets": "/assets"}
            c.monitor = "HDMI-A-1"
            c.data = {}
            process = Mock(pid=123)
            process.poll.return_value = None
            calls = 0
            def hypr(what):
                nonlocal calls
                if what == "monitors":
                    return [{"name":"HDMI-A-1","width":1920,"height":1080}]
                calls += 1
                if calls == 4:
                    (root / "state/logs/1.log").write_text("VO: [libmpv] 1920x1080 nv12\n")
                return {"HDMI-A-1":{"levels":{"0":[{"namespace":"linux-wallpaperengine","pid":123}]}}}
            with patch("controller.CACHE", root / "cache"), patch("controller.STATE", root / "state"), \
                    patch("controller.hypr", side_effect=hypr), patch("controller.subprocess.Popen", return_value=process), \
                    patch("controller.shutil.which", return_value="/mock/linux-wallpaperengine"):
                await asyncio.wait_for(c.spawn({"id":"1","signature":"a","title":"Video","type":"video","path":"/item"}), 2)
            self.assertGreater(calls, 4)
            self.assertEqual(c.rendered, "1")


class SnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_lock_blocks_capture_but_does_not_latch_after_unlock(self):
        locked = True
        prepared_token = ""
        captures = 0
        async def command(*args, **kwargs):
            nonlocal captures
            if args[0] == "qs":
                return "true" if locked else "false"
            captures += 1
            Path(args[-1]).write_bytes(b"private fixture")
            return ""
        async def ipc(method, *args, **kwargs):
            nonlocal prepared_token
            if method == "prepare":
                prepared_token = json.loads(args[0])["token"]
                return "true"
            return json.dumps({"token": prepared_token, "ready": bool(prepared_token)})
        with tempfile.TemporaryDirectory() as tmp, patch.object(transition, "RUNTIME", Path(tmp)), \
                patch.object(transition, "load", return_value={}), patch.object(transition.shutil, "which", return_value="grim"), \
                patch.object(transition, "command", side_effect=command), patch.object(transition, "ipc", side_effect=ipc):
            monitors = [{"name":"HDMI-A-1","x":0,"y":0}]
            self.assertIsNone(await transition.Transition.prepare(monitors, {"x":0,"y":0}))
            self.assertEqual(captures, 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])
            locked = False
            effect = await transition.Transition.prepare(monitors, {"x":0,"y":0})
            self.assertIsNotNone(effect)
            self.assertEqual(captures, 1)
            await effect.cancel()
            self.assertFalse(effect.directory.exists())

    async def test_shell_unavailable_falls_back_without_leaving_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(transition, "RUNTIME", Path(tmp)), \
                patch.object(transition, "load", return_value={}), patch.object(transition.shutil, "which", return_value="grim"), \
                patch.object(transition, "command", new=AsyncMock(side_effect=RuntimeError("no shell"))):
            self.assertIsNone(await transition.Transition.prepare([], {"x":0,"y":0}))
            self.assertFalse(list(Path(tmp).iterdir()))

    async def test_cancelled_capture_removes_private_runtime_directory(self):
        entered = asyncio.Event()
        async def command(*args, **kwargs):
            if args[0] == "grim":
                entered.set()
                await asyncio.Event().wait()
            return "false"
        with tempfile.TemporaryDirectory() as tmp, patch.object(transition, "RUNTIME", Path(tmp)), \
                patch.object(transition, "load", return_value={}), patch.object(transition.shutil, "which", return_value="grim"), \
                patch.object(transition, "command", side_effect=command), patch.object(transition, "ipc", new=AsyncMock(return_value="{}")):
            task = asyncio.create_task(transition.Transition.prepare([{"name":"HDMI-A-1","x":0,"y":0}], {"x":0,"y":0}))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(list((Path(tmp)/"wallpaperengine-transition").iterdir()), [])

    async def test_failed_reveal_releases_snapshot_instead_of_covering_desktop(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "snapshot"
            folder.mkdir()
            (folder / "old.ppm").write_bytes(b"private old desktop")
            effect = transition.Transition("one", folder, 680)
            with patch.object(transition, "ipc", new=AsyncMock(side_effect=["false", ""])) as ipc:
                await effect.reveal({"scheme":{}})
                self.assertEqual(ipc.await_args_list[-1].args, ("cancel", "one"))
            self.assertFalse(folder.exists())


if __name__ == "__main__":
    unittest.main()
