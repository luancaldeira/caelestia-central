"""Opt-in live pixel check of exported window edges against the native client.

A temporary Kitty launcher is clicked in the actual app hub. The final exported
pose is held only for two still captures, then compared with the native window.
The same check runs after clicking the window in the minimized hub. No video is
recorded. Full captures are temporary; --artifacts retains only corner crops.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from PIL import Image, ImageChops, ImageStat

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--live", action="store_true", required=True)
parser.add_argument("--backend", choices=("wayland", "x11"), default="wayland")
parser.add_argument("--artifacts", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
pointer = root / "tests/desktop/virtual-pointer"
app_id = "caelestia-edge-check-" + args.backend
data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
desktop_file = data_home / "applications" / (app_id + ".desktop")


def run(*command):
    return subprocess.check_output(command, text=True, stderr=subprocess.PIPE).strip()


def ipc(target, method, *values):
    return run("qs", "-c", "caelestia", "ipc", "call", target, method, *values)


def clients():
    return json.loads(run("hyprctl", "clients", "-j"))


def drawer():
    return json.loads(ipc("windowdrawer", "info"))


def hub():
    return json.loads(ipc("minimized", "info"))


def wait(check, message, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = check()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError(message)


def click(x, y):
    run(str(pointer), str(round(x)), str(round(y)), "0", "click")


assert pointer.is_file(), "Run sh tests/desktop/build-pointer.sh first"
assert ipc("lock", "isLocked") == "false"
assert not drawer()["count"], "Wait for the active transition to finish"
assert not desktop_file.exists(), "The diagnostic launcher already exists"
assert not any(c["workspace"]["name"] == "918" for c in clients())
monitors = json.loads(run("hyprctl", "monitors", "-j"))
assert len(monitors) == 1 and monitors[0]["width"] == 1920 and monitors[0]["height"] == 1080
assert monitors[0]["scale"] == 1 and monitors[0]["transform"] == 0

original_clients = {(c["address"], c["pid"]) for c in clients()}
original_entries = json.loads(ipc("minimized", "list"))
original_favorites = json.loads(ipc("appcentral", "info"))["favorites"]
active = json.loads(run("hyprctl", "activewindow", "-j"))
workspace = json.loads(run("hyprctl", "activeworkspace", "-j"))["name"]
cursor = json.loads(run("hyprctl", "cursorpos", "-j"))
before = hub()
owned = None
report = {"backend": args.backend, "passed": False, "cases": {}}


def current():
    if not owned:
        return None
    return next((f for f in drawer()["active"] if f["address"] == owned["address"][2:]), None)


def compare_handoff(action, directory):
    def final_pose():
        frame = current()
        return frame if frame and frame.get("awaitingPose") and frame["finalPoseSwaps"] >= 2 else None

    frame = wait(final_pose, "The exported final pose was not reached")
    assert frame["decorated"] and frame["edgeErrorPx"] == 0 and frame["elasticity"] == 0, frame
    roi = f'{round(frame["x"])},{round(frame["y"])} {round(frame["width"])}x{round(frame["height"])}'
    exported = directory / (action + "-exported.png")
    native = directory / (action + "-native.png")
    run("grim", "-g", roi, str(exported))
    held = current()
    assert held and not held["releaseRequestedAt"], "The native timeout expired during capture"
    ipc("windowdrawer", "hold", "false")
    wait(lambda: not current(), "The native handoff did not finish")
    time.sleep(0.06)
    run("grim", "-g", roi, str(native))
    done = next(f for f in drawer()["recent"] if f["token"] == frame["token"] and f["address"] == frame["address"]
                and f["pid"] == frame["pid"] and f["receivedAt"] == frame["receivedAt"])
    assert not done["handoffFallback"], done

    a = Image.open(exported).convert("RGB")
    b = Image.open(native).convert("RGB")
    width, height = a.size
    regions = {
        "left": (0, 40, 12, height - 40),
        "right": (width - 12, 40, width, height - 40),
        # The live hub stays above the native client after restore and its empty
        # state animates independently. Compare the exposed bottom edge on both
        # sides, rather than attributing that foreground animation to the window.
        "bottomLeft": (40, height - 12, width // 3, height),
        "bottomRight": (2 * width // 3, height - 12, width - 40, height),
        "titleBackground": (40, 0, 300, max(1, round(frame["captureTop"]))),
        "titleText": (width // 2 - 160, 0, width // 2 + 160, max(1, round(frame["captureTop"]))),
        "topLeft": (0, 0, 64, 64),
        "topRight": (width - 64, 0, width, 64),
    }
    errors = {
        name: ImageStat.Stat(ImageChops.difference(a.crop(box), b.crop(box))).mean
        for name, box in regions.items()
    }
    report["cases"][action] = {"meanColorError": errors, "sourceSize": [frame["sourceWidth"], frame["sourceHeight"]],
                                "maxFrameMs": done["maxFrameMs"], "handoffFallback": done["handoffFallback"]}
    print(action, json.dumps(report["cases"][action]), flush=True)
    if args.artifacts:
        args.artifacts.mkdir(parents=True, exist_ok=True)
        comparison = Image.new("RGB", (320, 160))
        comparison.paste(a.crop((0, 0, 160, 160)), (0, 0))
        comparison.paste(b.crop((0, 0, 160, 160)), (160, 0))
        comparison.save(args.artifacts / (args.backend + "-" + action + "-corners.png"))
    assert max(max(error) for error in errors.values()) < 10, errors


try:
    desktop_file.parent.mkdir(parents=True, exist_ok=True)
    desktop_file.write_text(
        "[Desktop Entry]\nType=Application\nName=Caelestia edge check\nIcon=kitty\n"
        f'Exec=kitty --class {app_id} --title "Caelestia edge check" '
        f"-o linux_display_server={args.backend} -o background_opacity=1 "
        "-o background=#263844 -o cursor_blink_interval=0 -o shell_integration=disabled cat\n"
        f"StartupWMClass={app_id}\nStartupNotify=false\nTerminal=false\n"
    )

    def launcher_ready():
        ipc("appcentral", "refresh")
        return any(app["id"] == app_id for app in json.loads(ipc("appcentral", "list")))

    wait(launcher_ready, "The temporary diagnostic launcher was not discovered")
    if hub()["open"]:
        ipc("minimized", "toggle")
    run("hyprctl", "dispatch", 'hl.dsp.focus({workspace="918"})')
    time.sleep(0.4)
    ipc("windowdrawer", "hold", "true")
    ipc("appcentral", "favorite", app_id)
    ipc("minimized", "toggle")
    time.sleep(0.6)
    panel = hub()
    index = panel["icons"].index(app_id)
    x = panel["mini"]["x"] + 30 + 46 * (index % 12)
    y = panel["mini"]["y"] + 28 + 46 * (index // 12)
    click(x, y)
    owned = wait(lambda: next((c for c in clients() if c["class"].lower() == app_id), None), "The actual app-hub click did not launch Kitty")
    assert owned["xwayland"] == (args.backend == "x11"), owned
    with tempfile.TemporaryDirectory(prefix="central-edge-crops-") as directory:
        directory = Path(directory)
        compare_handoff("open", directory)
        ipc("minimized", "minimizeWindow", owned["address"])
        wait(lambda: any(c["address"] == owned["address"] and c["workspace"]["name"] == "special:caelestia-minimized" for c in clients()), "The fixture did not minimize")
        ipc("windowdrawer", "hold", "true")
        if not hub()["open"]:
            ipc("minimized", "toggle")
        ipc("minimized", "tab", "1")
        run(str(pointer), "960", "900")
        time.sleep(0.65)
        for method in ("next", "previous"):
            for _ in range(len(original_entries) + 2):
                if hub().get("selected") == owned["address"][2:]:
                    break
                ipc("minimized", method)
            if hub().get("selected") == owned["address"][2:]:
                break
        assert hub().get("selected") == owned["address"][2:]
        origin = hub()["origin"]
        click(origin["x"] + origin["width"] / 2, origin["y"] + origin["height"] / 2)
        compare_handoff("restore", directory)
        assert hub()["open"], "The minimized hub closed during restoration"
finally:
    ipc("windowdrawer", "hold", "false")
    if owned and any(c["address"] == owned["address"] and c["pid"] == owned["pid"] for c in clients()):
        run("hyprctl", "dispatch", "hl.dsp.window.close({window=" + json.dumps("address:" + owned["address"]) + "})")
        wait(lambda: not any(c["address"] == owned["address"] and c["pid"] == owned["pid"] for c in clients()), "The diagnostic window did not close")
    if app_id in json.loads(ipc("appcentral", "info"))["favorites"]:
        ipc("appcentral", "favorite", app_id)
    desktop_file.unlink(missing_ok=True)
    ipc("appcentral", "refresh")
    if hub()["open"]:
        ipc("minimized", "toggle")
    if active.get("address"):
        run("hyprctl", "dispatch", "hl.dsp.focus({window=" + json.dumps("address:" + active["address"]) + "})")
    else:
        run("hyprctl", "dispatch", "hl.dsp.focus({workspace=" + json.dumps(workspace) + "})")
    if before["open"]:
        ipc("minimized", "toggle")
        ipc("minimized", "tab", str(before["tab"]))
        if before["tab"] == 0 and before["menuOpen"]:
            time.sleep(0.55)
            handle = hub()["handle"]
            click(handle["x"], handle["y"])
    run(str(pointer), str(cursor["x"]), str(cursor["y"]))
    (root / "test-results").mkdir(exist_ok=True)
    (root / f"test-results/edges-{args.backend}.json").write_text(json.dumps(report, indent=2))

assert original_clients <= {(c["address"], c["pid"]) for c in clients()}
assert {e["address"] for e in original_entries} == {e["address"] for e in json.loads(ipc("minimized", "list"))}
assert json.loads(ipc("appcentral", "info"))["favorites"] == original_favorites
report["passed"] = True
(root / f"test-results/edges-{args.backend}.json").write_text(json.dumps(report, indent=2))
