"""Regression checks for cold user services, compositor readiness and duplicate hooks."""
from concurrent.futures import ThreadPoolExecutor
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
loader = importlib.machinery.SourceFileLoader("wallpaperctl_cli", str(ROOT / "wallpaperctl"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class BootstrapTests(unittest.TestCase):
    def test_unloaded_service_starts_without_reset_failed(self):
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            if "reset-failed" in command:
                raise subprocess.CalledProcessError(1, command, stderr="Unit not loaded")
            return SimpleNamespace(returncode=0)
        with patch.object(cli.subprocess, "run", side_effect=run), \
                patch.object(cli, "call", return_value={"running": True, "busy": False}):
            self.assertTrue(cli.ensure_service(restart=True)["running"])
        self.assertIn(["systemctl", "--user", "restart", "wallpaperengine.service"], commands)

    def test_ready_bootstrap_waits_for_renderer_even_without_restart(self):
        ready = {"running": True, "busy": False}
        with patch.object(cli.subprocess, "run"), patch.object(cli.time, "sleep"), \
                patch.object(cli, "call", side_effect=[{"running": False, "busy": True}, ready]) as call:
            self.assertEqual(cli.ensure_service(ready=True), ready)
        self.assertEqual(call.call_count, 2)

    def test_waits_for_current_instance_and_complete_monitor(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "wayland-new").touch()
            monitor_calls = 0
            def run(command, **kwargs):
                nonlocal monitor_calls
                if command[1] == "instances":
                    data = [{"instance": "old", "wl_socket": "wayland-old"},
                            {"instance": "new", "wl_socket": "wayland-new"}]
                else:
                    self.assertEqual(command[1:3], ["-i", "new"])
                    monitor_calls += 1
                    data = [{"width": 1920, "height": 0 if monitor_calls == 1 else 1080}]
                return SimpleNamespace(stdout=json.dumps(data))
            with patch.object(cli, "RUNTIME", runtime), patch.object(cli.subprocess, "run", side_effect=run):
                self.assertEqual(cli.wait_for_compositor("new", interval=0), "wayland-new")
            self.assertEqual(monitor_calls, 2)

    def test_missing_compositor_times_out_instead_of_importing_old_display(self):
        with patch.object(cli.subprocess, "run", return_value=SimpleNamespace(stdout="[]")):
            with self.assertRaisesRegex(RuntimeError, "did not become ready"):
                cli.wait_for_compositor("gone", timeout=0)

    def test_duplicate_hooks_restart_once_and_replace_the_previous_session_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = {"session": "previous", "wayland_display": "wayland-old", "running": True}
            restarts = []
            def ensure(restart=False, ready=False):
                restarts.append(restart)
                self.assertTrue(ready)
                self.assertEqual(os.environ["WAYLAND_DISPLAY"], "wayland-new")
                state.update(session="new", wayland_display="wayland-new", running=True, busy=False, service_pid=123)
                return dict(state)
            with patch.object(cli, "STATE", root / "state"), patch.object(cli, "RUNTIME", root), \
                    patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "new", "WAYLAND_DISPLAY": "wayland-old"}), \
                    patch.object(cli, "wait_for_compositor", return_value="wayland-new"), \
                    patch.object(cli, "call", side_effect=lambda _: dict(state)), \
                    patch.object(cli, "ensure_service", side_effect=ensure):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: cli.session(), range(2)))
            self.assertEqual(restarts, [True, False])
            self.assertTrue(all(result["session"] == "new" for result in results))
            self.assertIn("renderer ready", (root / "state/logs/session.log").read_text())

    def test_bootstrap_error_is_recorded_for_login_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(cli, "STATE", root / "state"), patch.object(cli, "RUNTIME", root), \
                    patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "new"}), \
                    patch.object(cli, "wait_for_compositor", side_effect=RuntimeError("no active output")):
                with self.assertRaisesRegex(RuntimeError, "no active output"):
                    cli.session()
            self.assertIn("startup failed: no active output", (root / "state/logs/session.log").read_text())
