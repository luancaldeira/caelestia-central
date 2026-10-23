"""Short lived snapshot above live content; the GPU reveals the new desktop.

Only the old frame is captured. The new wallpaper remains the real, animated
engine below it. Snapshots live in private runtime memory and are promptly freed.
"""
import asyncio
import json
import logging
import os
from pathlib import Path
import shutil
import time
import uuid

from catalog import CONFIG, RUNTIME, load

LOG = logging.getLogger("wallpaperengine.transition")


async def command(*args, timeout=2):
    process = await asyncio.create_subprocess_exec(*map(str, args), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(err.decode(errors="replace").strip() or f"{args[0]} exited {process.returncode}")
    return out.decode(errors="replace").strip()


async def ipc(method, *args, timeout=.8):
    return await command("qs", "-c", "caelestia", "ipc", "call", "wallpapertransition", method, *args, timeout=timeout)


class Transition:
    def __init__(self, token, directory, duration):
        self.token, self.directory, self.duration = token, directory, duration

    @classmethod
    async def prepare(cls, monitors, origin):
        settings = (load(CONFIG / "settings.json", {}) or {}).get("transition", {})
        if settings.get("enabled", True) is False or not shutil.which("grim"):
            return None
        directory, transition = None, None
        try:
            locked = await command("qs", "-c", "caelestia", "ipc", "call", "lock", "isLocked", timeout=.5)
            if locked != "false":
                return None
            await ipc("info", timeout=.4)  # Fail immediately if the shell is unavailable.
            duration = max(180, min(1200, int(settings.get("duration_ms", 680))))
            token = uuid.uuid4().hex
            root = RUNTIME / "wallpaperengine-transition"
            root.mkdir(mode=0o700, exist_ok=True)
            # Clean up leftovers from an interrupted service/session.
            for old in root.iterdir():
                if old.is_dir() and time.time() - old.stat().st_mtime > 30:
                    shutil.rmtree(old, ignore_errors=True)
            directory = root / token
            directory.mkdir(mode=0o700)
            transition = cls(token, directory, duration)
            outputs = {}
            async def capture(index, monitor):
                path = directory / f"{index}.ppm"
                # PPM avoids PNG compression/decompression on the switch path.
                await command("grim", "-t", "ppm", "-o", monitor["name"], path, timeout=1.2)
                os.chmod(path, 0o600)
                outputs[monitor["name"]] = {"path": str(path), "x": monitor["x"], "y": monitor["y"]}
            async with asyncio.TaskGroup() as group:
                for n, monitor in enumerate(monitors):
                    if not monitor.get("disabled"):
                        group.create_task(capture(n, monitor))
            if not outputs:
                raise RuntimeError("No capture output")
            payload = {"token": token, "frames": outputs, "origin": origin, "duration": duration,
                       "reduced": bool(settings.get("reduce_motion")) or os.environ.get("CAELESTIA_REDUCED_MOTION") == "1"}
            if await ipc("prepare", json.dumps(payload)) != "true":
                raise RuntimeError("Shell declined transition")
            # Wait for a real frame swap, not an arbitrary animation delay.
            deadline = time.monotonic() + .45
            while time.monotonic() < deadline:
                state = json.loads(await ipc("info"))
                if state.get("token") == token and state.get("ready"):
                    return transition
                await asyncio.sleep(.008)
            raise RuntimeError("Snapshot overlay did not become ready")
        except asyncio.CancelledError:
            if transition:
                await transition.cancel()
            elif directory:
                shutil.rmtree(directory, ignore_errors=True)
            raise
        except Exception:
            LOG.debug("Spatial transition unavailable; switching directly", exc_info=True)
            if transition:
                await transition.cancel()
            elif directory:
                shutil.rmtree(directory, ignore_errors=True)
            return None

    async def reveal(self, theme):
        try:
            if await ipc("reveal", self.token, json.dumps(theme["scheme"])) != "true":
                return
            # The animation itself never blocks the next request.
            await asyncio.sleep(self.duration / 1000 + .12)
        except Exception:
            LOG.debug("Transition reveal ended early", exc_info=True)
        finally:
            await self.cancel()

    async def cancel(self):
        try:
            await ipc("cancel", self.token)
        except Exception:
            pass
        shutil.rmtree(self.directory, ignore_errors=True)
