"""Single-owner renderer controller and local IPC server."""
import asyncio
import ctypes
import fcntl
import json
import logging
import os
import random
import shutil
import signal
import subprocess
import time
from pathlib import Path

from catalog import CACHE, CONFIG, STATE, RUNTIME, atomic, load, scan
import palette
import previews
import greeter
from transition import Transition

SOCKET = RUNTIME / "wallpaperengine.sock"
LOG = logging.getLogger("wallpaperengine")
ENGINE = Path("/opt/linux-wallpaperengine/linux-wallpaperengine")


def hypr(what):
    p = subprocess.run(["hyprctl", what, "-j"], capture_output=True, text=True, timeout=3)
    if p.returncode:
        raise RuntimeError("Could not query the Hyprland session.")
    return json.loads(p.stdout)


def session_present():
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    return bool(signature and (RUNTIME / "hypr" / signature / ".socket.sock").exists())


def existing_renderers():
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            if p.stat().st_uid == os.getuid() and (p / "exe").resolve() == ENGINE:
                yield int(p.name)
        except OSError:
            pass


async def startup_catalog(restore, timeout=90, interval=2):
    """Wait for boot dependencies without replacing a temporarily absent selection."""
    deadline = time.monotonic() + timeout
    last_reason = None
    while True:
        catalog = await asyncio.to_thread(scan)
        chosen = next((i for i in catalog["items"] if i["id"] == str(restore) and not i["missing"]), None)
        fallback = next((i for i in catalog["items"] if i["type"] == "video" and not i["missing"]), None)
        try:
            monitors = await asyncio.to_thread(hypr, "monitors")
            ready = any(not m.get("disabled") and m.get("width", 0) > 0 and m.get("height", 0) > 0 for m in monitors)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            ready = False
        if ready and catalog["assets"] and (chosen or (not restore and fallback)):
            return catalog, chosen or fallback
        expired = time.monotonic() >= deadline
        if expired and ready and catalog["assets"] and fallback:
            LOG.warning("Saved wallpaper unavailable after boot grace period; using %s", fallback["id"])
            return catalog, fallback
        reason = ("Hyprland session/monitor" if not ready else
                  "Steam assets" if not catalog["assets"] else "saved Workshop wallpaper")
        if expired:
            raise RuntimeError(f"Startup is waiting for {reason}; the service will retry.")
        if reason != last_reason:
            LOG.info("Waiting for %s before restoring the wallpaper", reason)
            last_reason = reason
        await asyncio.sleep(interval)


class Controller:
    def __init__(self):
        self.data = load(STATE / "selection.json", {}) or {}
        self.data.setdefault("favorites", [])
        self.data.setdefault("recent", [])
        self.data.setdefault("preferences", {})
        self.data.setdefault("compatibility", {})
        self.catalog = scan()
        self.process = None
        self.rendered = ""
        self.monitor = ""
        self.aspect = 16/9
        self.display_signature = None
        self.busy = False
        self.switching = False
        self.message = "Preparing wallpaper…"
        self.error = ""
        self.theme = load(STATE / "active-theme.json", {})
        self.preview = {}
        self.generation = 0
        self.preview_generation = 0
        self.preview_lock = asyncio.Lock()
        self.pending = None
        self.wake = asyncio.Event()
        self.closing = asyncio.Event()
        self.refreshing = False
        self.recovery_delay = 4
        self.recovery_at = 0
        self.stable_since = None
        self.started = time.monotonic()
        self.loop = asyncio.get_running_loop()
        self.watch_fd = None
        self.refresh_timer = None
        self.poster_task = None
        self.login_task = None
        self.transition_tasks = set()
        self.held_transition = None
        self.last_switch = {}

    async def theme_for(self, item, force=False):
        prefs = dict(self.data["preferences"].get(item["id"], {}))
        frozen = load(STATE / "themes" / f'{item["id"]}.json') if prefs.get("frozen") else None
        capture = CACHE / "renders" / f'{item["id"]}-{item["signature"]}.png'
        return frozen or await asyncio.to_thread(palette.cached_theme, item, self.aspect, prefs, force, capture)

    def queue_posters(self):
        if self.poster_task is None or self.poster_task.done():
            self.poster_task = asyncio.create_task(self.prepare_posters())

    async def prepare_posters(self):
        # Decode off the event loop: Steam sync, hover and IPC stay responsive.
        # Re-read the list after a refresh so a download/removal during decoding
        # cannot resurrect a stale card or strand a newly subscribed wallpaper.
        completed = set()
        while not self.closing.is_set():
            pending = [i for i in self.catalog["items"] if (i["id"], i["signature"], str(previews.key(i, CACHE)[0])) not in completed]
            if not pending:
                break
            item = pending[0]
            token = (item["id"], item["signature"], str(previews.key(item, CACHE)[0]))
            try:
                result = await asyncio.to_thread(previews.prepare, dict(item), CACHE)
                current = self.item(item["id"])
                if current and current["signature"] == item["signature"]:
                    if any(current.get(k) != v for k, v in result.items()):
                        current.update(result)
                        self.publish()
            except Exception:
                LOG.exception("Poster preparation failed for %s", item["id"])
            completed.add(token)
        # Posters get priority. Warm colours afterward, including items whose
        # posters finished while a wallpaper was still loading during login.
        for item in list(self.catalog["items"]):
            while self.busy and not self.closing.is_set():
                await asyncio.sleep(.1)
            if self.closing.is_set():
                return
            if not item.get("missing"):
                try:
                    await self.theme_for(item)
                except Exception:
                    LOG.debug("Palette prewarm unavailable for %s", item["id"], exc_info=True)

    def item(self, ident):
        return next((i for i in self.catalog["items"] if i["id"] == str(ident)), None)

    def login_source(self, item, theme):
        return (previews.cached_login_wallpaper(item, CACHE)
                or previews.cached(item, CACHE).get("displayPreview") or theme["poster"])

    def queue_login_wallpaper(self, item, generation):
        if self.login_task:
            self.login_task.cancel()
        self.login_task = asyncio.create_task(self.update_login_wallpaper(dict(item), generation))

    def export_greeter(self, source):
        try:
            greeter.export(source, self.theme.get("scheme"), load(CONFIG / "settings.json", {}))
        except Exception:
            LOG.exception("Could not export the login wallpaper")

    async def update_login_wallpaper(self, item, generation):
        """Prepare outside the transition, then upgrade once a scene capture arrives."""
        def current():
            return (not self.closing.is_set() and generation == self.generation
                    and self.rendered == item["id"])
        capture = CACHE / "renders" / f'{item["id"]}-{item["signature"]}.png'
        had_capture = capture.is_file()
        try:
            source = await asyncio.to_thread(previews.prepare_login_wallpaper, item, CACHE)
            if not current():
                return
            palette.apply_wallpaper_source(source)
            self.export_greeter(source)
            # The renderer writes a scene capture after its first presentation
            # frames. Do not leave the initial thumbnail as the next login image.
            if item["type"] == "scene" and not had_capture:
                deadline = time.monotonic() + 60
                while current() and not capture.is_file() and time.monotonic() < deadline:
                    await asyncio.sleep(.25)
                if current() and capture.is_file():
                    source = await asyncio.to_thread(previews.prepare_login_wallpaper, item, CACHE)
                    if current():
                        palette.apply_wallpaper_source(source)
                        self.export_greeter(source)
        except Exception:
            LOG.exception("Could not prepare the login wallpaper for %s", item["id"])

    def persist(self):
        atomic(STATE / "selection.json", self.data)

    def publish(self):
        items = []
        for item in self.catalog["items"]:
            item = {**item, "favorite": item["id"] in self.data["favorites"],
                    "recent": self.data["recent"].index(item["id"]) if item["id"] in self.data["recent"] else 999,
                    "compatibility": self.data["compatibility"].get(item["id"], {})}
            items.append(item)
        atomic(STATE / "status.json", {
            "items": items, "active": self.rendered or self.data.get("active", ""),
            "running": bool(self.process and self.process.poll() is None),
            "busy": self.busy, "switching": self.switching, "message": self.message, "error": self.error,
            "monitor": self.monitor, "theme": self.theme, "preview": self.preview,
            "preferences": self.data["preferences"], "assets": self.catalog["assets"],
            "updated": time.time(), "service_pid": os.getpid(),
            "session": os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", ""),
            "wayland_display": os.environ.get("WAYLAND_DISPLAY", ""),
            "lastSwitch": self.last_switch,
        })

    def request(self, ident, force=False):
        item = self.item(ident)
        if not item:
            raise ValueError("Wallpaper was not found in local Steam libraries.")
        if item["missing"]:
            raise ValueError("This item is incomplete or does not contain a usable project.")
        self.generation += 1
        self.pending = (item, force, self.generation)
        self.busy = True
        self.error = ""
        self.message = f'Preparing {item["title"]}…'
        self.publish()
        self.wake.set()

    async def stop_renderer(self, fast=False):
        process, self.process = self.process, None
        if process and process.poll() is None:
            process.terminate()
            deadline = time.monotonic() + (.25 if fast else 4)
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                await asyncio.sleep(.015 if fast else .1)
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
        self.rendered = ""

    async def spawn(self, item):
        if not self.catalog["assets"]:
            raise ValueError("Wallpaper Engine assets were not found in Steam libraries.")
        monitors = await asyncio.to_thread(hypr, "monitors")
        monitors = [m for m in monitors if not m.get("disabled")]
        if not monitors:
            raise ValueError("No active monitor was found.")
        primary = next((m for m in monitors if m["name"] == self.monitor),
                       next((m for m in monitors if m.get("focused")), monitors[0]))
        self.monitor = primary["name"]
        self.aspect = primary["width"] / primary["height"]
        if primary.get("transform", 0) % 2:
            self.aspect = 1 / self.aspect
        self.display_signature = [(m["name"], m["width"], m["height"], m.get("scale"), m.get("transform")) for m in monitors]
        self.data["monitor"] = self.monitor
        capture = CACHE / "renders" / f'{item["id"]}-{item["signature"]}.png'
        capture.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["/usr/bin/linux-wallpaperengine"]
        for monitor in monitors:
            cmd += ["--screen-root", monitor["name"], "--bg", item["path"], "--scaling", "fill"]
        cmd += ["--layer", "background", "--fps", "30", "--silent", "--assets-dir", self.catalog["assets"]]
        screenshot = item["type"] == "scene" and not capture.is_file()
        if screenshot:
            cmd += ["--screenshot", str(capture), "--screenshot-delay", "45"]
        logpath = STATE / "logs" / f'{item["id"]}.log'
        logpath.parent.mkdir(parents=True, exist_ok=True)
        with logpath.open("w") as out:
            out.write("Command: " + json.dumps(cmd, ensure_ascii=False) + "\n")
            out.flush()
            self.process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out)
        ready_since = None
        for _ in range(720):
            if self.process.poll() is not None:
                if screenshot and capture.is_file():
                    # Some engine versions take one image and exit intentionally.
                    screenshot = False
                    cmd = cmd[:-4]
                    with logpath.open("a") as out:
                        self.process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out)
                    continue
                detail = logpath.read_text(errors="replace")[-1200:]
                raise RuntimeError(f'The renderer could not load “{item["title"]}”. Log: {logpath}\n{detail}')
            layers = await asyncio.to_thread(hypr, "layers")
            output = layers.get(self.monitor, {}).get("levels", {})
            ready = any(layer.get("namespace") == "linux-wallpaperengine" and layer.get("pid") == self.process.pid
                        for layer in output.get("0", []))
            if ready and item["type"] == "video":
                # A mapped video surface can still contain only its black clear
                # buffer while mpv probes decoders. VO is the installed engine's
                # first decoded-video signal; only then count presentation frames.
                ready = "VO: [libmpv]" in logpath.read_text(errors="replace")
            if ready:
                ready_since = ready_since or time.monotonic()
                # Wait a couple of rendered frames; neither a fixed 1 s sleep
                # nor the optional 45-frame palette screenshot gates the switch.
                if time.monotonic() - ready_since >= .065:
                    self.rendered = item["id"]
                    return capture if capture.is_file() else None
            else:
                ready_since = None
            await asyncio.sleep(.025)
        # A valid layer may render even if this engine version cannot capture it.
        if ready and self.process.poll() is None:
            self.rendered = item["id"]
            return capture if capture.is_file() else None
        raise RuntimeError("The renderer did not create a background layer on the expected monitor.")

    async def worker(self):
        while True:
            await self.wake.wait()
            self.wake.clear()
            if not self.pending:
                continue
            item, force, generation = self.pending
            self.pending = None
            previous = self.item(self.data.get("active", ""))
            transition, self.held_transition = getattr(self, "held_transition", None), None
            switch_start = time.monotonic()
            timing = {"id": item["id"]}
            try:
                result, palette_error = None, None
                try:
                    # Prepare colours while the previous wallpaper stays live.
                    result = await self.theme_for(item, force)
                except Exception as e:
                    LOG.exception("Palette preparation failed")
                    palette_error = e
                timing["paletteMs"] = round((time.monotonic() - switch_start) * 1000)
                if generation != self.generation:
                    continue
                if self.rendered != item["id"] or not self.process or self.process.poll() is not None:
                    self.switching = True
                    self.publish()
                    if self.rendered and not transition:
                        monitors, origin = await asyncio.gather(asyncio.to_thread(hypr, "monitors"), asyncio.to_thread(hypr, "cursorpos"))
                        transition = await Transition.prepare(monitors, origin)
                    timing["preparedMs"] = round((time.monotonic() - switch_start) * 1000)
                    if generation != self.generation:
                        continue
                    stop_start = time.monotonic()
                    await self.stop_renderer(fast=True)
                    timing["stopMs"] = round((time.monotonic() - stop_start) * 1000)
                    render_start = time.monotonic()
                    await self.spawn(item)
                    timing["renderMs"] = round((time.monotonic() - render_start) * 1000)
                    self.switching = False
                if generation != self.generation:
                    continue
                self.data["active"] = item["id"]
                self.data["recent"] = [item["id"]] + [i for i in self.data["recent"] if i != item["id"]][:29]
                self.data["compatibility"][item["id"]] = {"state": "ok", "message": "Tested on this system"}
                self.persist()
                self.message = "Wallpaper is active."
                try:
                    if palette_error:
                        raise palette_error
                    palette.apply(result, self.login_source(item, result))
                    self.theme = result
                    atomic(STATE / "themes" / f'{item["id"]}.json', result)
                    atomic(STATE / "active-theme.json", result)
                    self.message = f'{item["title"]} · colors from {result["source"]}'
                    if transition:
                        task = asyncio.create_task(transition.reveal(result))
                        self.transition_tasks.add(task)
                        task.add_done_callback(self.transition_tasks.discard)
                        transition = None
                except Exception as e:
                    LOG.exception("Palette generation failed")
                    self.error = f"Wallpaper is active; the previous palette was preserved. {e}"
                    self.message = item["title"]
                timing["readyMs"] = round((time.monotonic() - switch_start) * 1000)
                self.last_switch = timing
                self.queue_login_wallpaper(item, generation)
            except Exception as e:
                LOG.exception("Wallpaper switch failed")
                self.error = str(e)
                self.data["compatibility"][item["id"]] = {"state": "error", "message": str(e).split("\n")[0]}
                await self.stop_renderer()
                if previous:
                    try:
                        await self.spawn(previous)
                        self.message = f'Restored: {previous["title"]}'
                    except Exception:
                        LOG.exception("Previous wallpaper could not be restored")
                        self.message = "Could not restore the previous wallpaper."
                self.persist()
            finally:
                if transition:
                    if self.pending and generation != self.generation and not self.closing.is_set():
                        # Keep the current picture when a newer click supersedes
                        # a renderer already loading. The next target reuses it.
                        self.held_transition = transition
                    else:
                        await transition.cancel()
                self.switching = False
                if not self.pending:
                    self.busy = False
                self.publish()

    async def make_preview(self, ident, force=False):
        self.preview_generation += 1
        token = self.preview_generation
        item = self.item(ident)
        if not item:
            return
        try:
            async with self.preview_lock:
                if token != self.preview_generation:
                    return
                capture = CACHE / "renders" / f'{item["id"]}-{item["signature"]}.png'
                result = await asyncio.to_thread(palette.cached_theme, item, self.aspect,
                                                dict(self.data["preferences"].get(item["id"], {})), force, capture)
            if token == self.preview_generation:
                self.preview = {"id": ident, **result}
                self.publish()
        except Exception as e:
            if token == self.preview_generation:
                self.preview = {"id": ident, "error": str(e)}
                self.publish()

    async def refresh(self):
        if self.refreshing:
            return
        self.refreshing = True
        try:
            previous = self.item(self.data.get("active", ""))
            self.catalog = await asyncio.to_thread(scan)
            self.setup_watch()
            current = self.item(self.data.get("active", ""))
            if previous and self.rendered:
                if not current or current["missing"]:
                    fallback = next((i for i in self.catalog["items"] if i["type"] == "video" and not i["missing"]
                                     and self.data["compatibility"].get(i["id"], {}).get("state") != "error"), None)
                    if fallback:
                        self.request(fallback["id"])
                        if shutil.which("notify-send"):
                            subprocess.Popen(["notify-send", "-a", "Steam Wallpapers", "Wallpaper removed from the library",
                                              f'Switching back to {fallback["title"]}.'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif current["signature"] != previous["signature"]:
                    self.request(current["id"])
                    self.rendered = ""
            self.publish()
        finally:
            self.queue_posters()
            self.refreshing = False

    def setup_watch(self):
        if self.watch_fd is not None:
            self.loop.remove_reader(self.watch_fd)
            os.close(self.watch_fd)
        libc = ctypes.CDLL(None, use_errno=True)
        fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        self.watch_fd = fd if fd >= 0 else None
        if fd < 0:
            return  # Explicit refresh and a slow fallback poll remain available.
        for path in self.catalog["watch"]:
            libc.inotify_add_watch(fd, os.fsencode(path), 0x00000008 | 0x00000040 | 0x00000080 | 0x00000100 | 0x00000200 | 0x00000400 | 0x00000800)
        def changed():
            try:
                os.read(fd, 65536)
            except BlockingIOError:
                return
            if self.refresh_timer:
                self.refresh_timer.cancel()
            self.refresh_timer = self.loop.call_later(1, lambda: asyncio.create_task(self.refresh()))
        self.loop.add_reader(fd, changed)

    async def handle(self, req):
        action = req.get("action")
        ident = str(req.get("id", ""))
        if action in ("list", "status"):
            return load(STATE / "status.json", {})
        if action == "refresh":
            await self.refresh()
        elif action == "apply":
            self.recovery_attempted = False
            self.request(ident)
        elif action == "restore":
            self.request(self.data.get("active") or "2855646333")
        elif action in ("next", "random"):
            eligible = [i for i in self.catalog["items"] if not i["missing"] and
                        i["type"] in ("scene", "video") and self.data["compatibility"].get(i["id"], {}).get("state") != "error"]
            if not eligible:
                raise ValueError("No wallpapers are available.")
            active = self.rendered or self.data.get("active")
            if action == "random":
                chosen = random.choice([i for i in eligible if i["id"] != active] or eligible)
            else:
                index = next((n for n, i in enumerate(eligible) if i["id"] == active), -1)
                chosen = eligible[(index + 1) % len(eligible)]
            self.request(chosen["id"])
        elif action == "favorite":
            if not self.item(ident):
                raise ValueError("Item not found.")
            values = self.data["favorites"]
            values.remove(ident) if ident in values else values.append(ident)
            self.persist()
        elif action == "preview":
            asyncio.create_task(self.make_preview(ident))
        elif action == "theme-options":
            if not self.item(ident):
                raise ValueError("Item not found.")
            options = req.get("options", {})
            allowed = {"intensity": ("equilibrada", "viva"), "mode": ("dark", "light", "auto")}
            pref = self.data["preferences"].setdefault(ident, {})
            for key, value in options.items():
                if key in allowed and value in allowed[key]:
                    pref[key] = value
                elif key == "frozen" and isinstance(value, bool):
                    pref[key] = value
                elif key == "seed" and (value is None or (isinstance(value, str) and len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value))):
                    pref[key] = value
                else:
                    raise ValueError("Invalid theme preference.")
            if any(key in options for key in ("intensity", "mode", "seed")):
                pref["frozen"] = False
            self.persist()
            if ident == self.rendered:
                self.request(ident)
            asyncio.create_task(self.make_preview(ident))
        elif action == "recolor":
            if not self.item(ident):
                raise ValueError("Item not found.")
            self.data["preferences"].setdefault(ident, {})["frozen"] = False
            self.persist()
            if ident == self.rendered:
                self.request(ident, force=True)
            else:
                asyncio.create_task(self.make_preview(ident, force=True))
        elif action == "undo-theme":
            previous = load(STATE / "previous-scheme.json")
            if not previous:
                raise ValueError("No previous palette has been saved.")
            result = {**self.theme, "scheme": previous, "source": "previous palette"}
            item = self.item(self.rendered or self.data.get("active", ""))
            try:
                source = (STATE.parent / "caelestia/wallpaper/path.txt").read_text().strip()
            except OSError:
                source = ""
            source = (source if source and Path(source).is_file()
                      else self.login_source(item, result) if item else result["poster"])
            palette.apply(result, source)
            self.theme = result
            self.export_greeter(source)
            atomic(STATE / "active-theme.json", result)
            if self.rendered:
                atomic(STATE / "themes" / f"{self.rendered}.json", result)
                self.data["preferences"].setdefault(self.rendered, {})["frozen"] = True
                self.persist()
            self.message = "The previous palette was restored and pinned to this wallpaper."
        else:
            raise ValueError("Unknown action.")
        self.publish()
        return {"accepted": True}

    async def client(self, reader, writer):
        try:
            raw = await asyncio.wait_for(reader.readline(), 5)
            req = json.loads(raw)
            reply = {"ok": True, "data": await self.handle(req)}
        except Exception as e:
            reply = {"ok": False, "error": str(e)}
        writer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def health(self):
        ticks = 0
        misses = 0
        while not self.closing.is_set():
            await asyncio.sleep(4)
            ticks += 1
            try:
                monitors = await asyncio.to_thread(hypr, "monitors")
                misses = 0
                signature = [(m["name"], m["width"], m["height"], m.get("scale"), m.get("transform"))
                             for m in monitors if not m.get("disabled")]
                if self.display_signature and signature != self.display_signature and not self.busy and self.data.get("active"):
                    self.request(self.data["active"])
                    # Force the same item to remap to the new output configuration.
                    self.rendered = ""
            except Exception:
                misses += 1
                if misses >= 3:
                    if session_present():
                        raise RuntimeError("The session exists, but Hyprland IPC is not responding; restarting the controller.")
                    self.closing.set()
            running = self.process and self.process.poll() is None
            now = time.monotonic()
            if running:
                self.stable_since = self.stable_since or now
                if now - self.stable_since >= 60:
                    self.recovery_delay = 4
            else:
                self.stable_since = None
            if not self.closing.is_set() and not self.busy and not running and now >= self.recovery_at:
                item = self.item(self.data.get("active", ""))
                self.recovery_at = now + self.recovery_delay
                self.recovery_delay = min(60, self.recovery_delay * 2)
                if item and not item["missing"]:
                    LOG.warning("Renderer stopped; restoring %s", item["id"])
                    self.request(item["id"])
            if ticks % 15 == 0:
                await self.refresh()

    async def run(self):
        self.monitor = self.data.get("monitor", "")
        # systemd owns this wait/retry, so boot ordering cannot leave an active
        # controller with no renderer simply because Steam/outputs were late.
        self.catalog, chosen = await startup_catalog(self.data.get("active"))
        # Migrate the manually launched engine. Verify actual executable and UID;
        # never match command text (which can include this script's own command).
        for pid in existing_renderers():
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for _ in range(50):
            if not list(existing_renderers()):
                break
            await asyncio.sleep(.1)
        if list(existing_renderers()):
            raise RuntimeError("A previous renderer did not stop; a second instance was not started.")
        self.engine_lock = (RUNTIME / "linux-wallpaperengine.lock").open("w")
        fcntl.flock(self.engine_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if shutil.which("awww"):
            subprocess.run(["awww", "kill"], capture_output=True, timeout=3)
        SOCKET.unlink(missing_ok=True)
        server = await asyncio.start_unix_server(self.client, path=SOCKET, limit=65536)
        os.chmod(SOCKET, 0o600)
        self.setup_watch()
        self.queue_posters()
        for sig in (signal.SIGTERM, signal.SIGINT):
            self.loop.add_signal_handler(sig, self.closing.set)
        self.publish()
        if chosen:
            self.request(chosen["id"])
        tasks = [asyncio.create_task(self.worker()), asyncio.create_task(self.health())]
        failures = []
        def supervise(task):
            if not task.cancelled() and not self.closing.is_set():
                failures.append(task.exception() or RuntimeError("A controller task stopped unexpectedly."))
                self.closing.set()
        for task in tasks:
            task.add_done_callback(supervise)
        try:
            await self.closing.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.poster_task:
                self.poster_task.cancel()
                await asyncio.gather(self.poster_task, return_exceptions=True)
            if self.login_task:
                self.login_task.cancel()
                await asyncio.gather(self.login_task, return_exceptions=True)
            for task in self.transition_tasks:
                task.cancel()
            await asyncio.gather(*self.transition_tasks, return_exceptions=True)
            if self.held_transition:
                await self.held_transition.cancel()
                self.held_transition = None
            await self.stop_renderer()
            server.close()
            await server.wait_closed()
            SOCKET.unlink(missing_ok=True)
            if self.watch_fd is not None:
                self.loop.remove_reader(self.watch_fd)
                os.close(self.watch_fd)
            self.busy = False
            self.message = "Controller stopped."
            self.publish()
        if failures:
            raise RuntimeError("Internal failure; systemd will restart the controller.") from failures[0]


def serve():
    STATE.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with (RUNTIME / "wallpaperengine-controller.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("The controller is already running.")
        async def main():
            await Controller().run()
        asyncio.run(main())
