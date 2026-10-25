"""Opt-in native shadow and populated application-content regression.

Click a temporary favorite that opens Dolphin on /usr/share/applications, then
minimize and restore it through the real hub. --floating exposes all four shadow
margins during restoration. The default compares held exported/native frames;
--normal-speed samples the actual landing without pausing or slowing it.

The test asserts native shadow margins, nonempty app content, pixel continuity,
atomic handoff, and preservation of the original windows/favorites/pointer. It
uses uncompressed stills, never a video recorder. Full captures are temporary;
--artifacts retains only public-directory content and shadow crops for review.
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
parser.add_argument("--floating", action="store_true", help="Expose all four shadow margins during restore")
parser.add_argument("--normal-speed", action="store_true", help="Sample the real landing without holding or slowing the animation")
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
pointer = root / "tests/desktop/virtual-pointer"
app_id = "caelestia-content-check-" + args.backend
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
report = {"app": "Dolphin", "floatingRestore": args.floating, "backend": args.backend, "normalSpeed": args.normal_speed, "passed": False, "cases": {}}


def current():
    if not owned:
        return None
    return next((f for f in drawer()["active"] if f["address"] == owned["address"][2:]), None)


def compare_handoff(action, directory):
    if args.normal_speed:
        return compare_normal_handoff(action, directory)
    def final_pose():
        frame = current()
        return frame if frame and frame.get("awaitingPose") and frame["finalPoseSwaps"] >= 2 else None

    frame = wait(final_pose, "The exported final pose was not reached")
    assert frame["decorated"] and frame["edgeErrorPx"] == 0 and frame["elasticity"] == 0, frame
    roi = f'{round(frame["x"])},{round(frame["y"])} {round(frame["width"])}x{round(frame["height"])}'
    exported = directory / (action + "-exported.png")
    native = directory / (action + "-native.png")
    run("grim", "-l", "0", "-g", roi, str(exported))
    held = current()
    assert held and not held["releaseRequestedAt"], "The native timeout expired during capture"
    ipc("windowdrawer", "hold", "false")
    wait(lambda: not current(), "The native handoff did not finish")
    time.sleep(0.06)
    run("grim", "-l", "0", "-g", roi, str(native))
    done = next(f for f in drawer()["recent"] if f["token"] == frame["token"] and f["address"] == frame["address"]
                and f["pid"] == frame["pid"] and f["receivedAt"] == frame["receivedAt"])
    assert not done["handoffFallback"], done
    assert done["atomicHandoff"], done

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
    left, top, right, bottom = frame["shadowPadding"]
    assert min(left, top, right, bottom) > 0, "Enable native shadows for this check"
    left, top, right, bottom = map(round, (left, top, right, bottom))
    regions.update({
        "shadowLeft": (0, top+64, left, height-bottom-64),
        "shadowRight": (width-right, top+64, width, height-bottom-64),
        "shadowTop": (left+64, 0, width-right-64, top),
        "shadowBottomLeft": (left+64, height-bottom, width//3, height),
        "shadowBottomRight": (2*width//3, height-bottom, width-right-64, height),
        "content": (left+180, top+40, min(width-right-20,left+800), min(height-bottom-20,top+280)),
    })
    assert max(ImageStat.Stat(a.crop(regions["content"])).stddev) > 15, "The app content was empty"
    errors = {
        name: ImageStat.Stat(ImageChops.difference(a.crop(box), b.crop(box))).mean
        for name, box in regions.items()
    }
    report["cases"][action] = {"meanColorError": errors, "sourceSize": [frame["sourceWidth"], frame["sourceHeight"]],
                                "shadowPadding": frame["shadowPadding"], "maxFrameMs": done["maxFrameMs"], "handoffFallback": done["handoffFallback"]}
    print(action, json.dumps(report["cases"][action]), flush=True)
    if args.artifacts:
        args.artifacts.mkdir(parents=True, exist_ok=True)
        comparison = Image.new("RGB", (320, 160))
        comparison.paste(a.crop((0, 0, 160, 160)), (0, 0))
        comparison.paste(b.crop((0, 0, 160, 160)), (160, 0))
        comparison.save(args.artifacts / (args.backend + "-" + action + "-corners.png"))
    checked = {name:error for name,error in errors.items() if name.startswith("shadow") or name=="content"}
    assert max(max(error) for error in checked.values()) < 10, checked



def compare_normal_handoff(action, directory):
    frame = wait(lambda: (f if (f := current()) and f["startedAt"] else None), "The transition did not animate")
    # A narrow strip covers the title and both upper corners. Uncompressed
    # stills avoid a video encoder and keep the desktop's normal frame timing.
    x = round(frame["x"])
    y = round(owned["at"][1] - frame["captureTop"])
    width = round(frame["width"])
    roi = f"{x},{y} {width}x360"
    samples = []
    deadline = frame["startedAt"] + 800
    time.sleep(max(0, (frame["startedAt"] + 250 - time.time() * 1000) / 1000))
    while time.time() * 1000 < deadline:
        path = directory / f"{action}-{len(samples)}.png"
        start = time.time() * 1000
        run("grim", "-l", "0", "-g", roi, str(path))
        samples.append((start, time.time() * 1000, path))
    wait(lambda: not current(), "The normal native handoff did not finish")
    done = next(f for f in drawer()["recent"] if f["token"] == frame["token"] and f["address"] == frame["address"]
                and f["pid"] == frame["pid"] and f["receivedAt"] == frame["receivedAt"])
    assert not done["handoffFallback"], done
    assert done["atomicHandoff"], done
    landing_end = done["landingStartedAt"] + done["landingDuration"]
    # A screencopy request may start just before the final landing frame. Keep
    # its complete request interval before release, and still require pixel
    # continuity. Never hold the pose to make a sample fit this interval.
    before = [s for s in samples if s[0] >= landing_end - 25 and s[1] < done["releaseRequestedAt"]]
    after = [s for s in samples if s[0] > done["completedAt"]]
    assert before and after, {"message": "No still straddled the real handoff", "done": done,
                              "samples": [[a-frame["startedAt"], b-frame["startedAt"]] for a,b,_ in samples]}
    a = Image.open(before[-1][2]).convert("RGB")
    b = Image.open(after[-1][2]).convert("RGB")
    regions = {"left": (0, 40, 12, 100), "right": (width-12, 40, width, 100),
               "topLeft": (0, 0, 64, 64), "topRight": (width-64, 0, width, 64),
               "titleBackground": (40, 0, 300, round(frame["captureTop"])),
               "titleText": (width//2-160, 0, width//2+160, round(frame["captureTop"]))}
    left, top, right, bottom = map(round, frame["shadowPadding"])
    assert min(left, top, right, bottom) > 0, "Native shadow margins were missing"
    regions.update({
        # Compare exposed shadow pixels, excluding the shell border/bar that
        # clips both the moving image and the native client underneath it.
        "shadowLeft": (max(0,round(frame["clipBounds"][0]-x)), top+64, left, 360),
        "shadowRight": (width-right, top+64, min(width,round(frame["clipBounds"][2]-x)), 360),
        "shadowTop": (left+64, max(0,round(frame["clipBounds"][1]-y)), width-right-64, top),
        "content": (left+180, top+40, min(width-right-20,left+800), min(340,top+280)),
    })
    assert max(ImageStat.Stat(b.crop(regions["content"])).stddev) > 15, "The app content was empty"
    errors = {name: ImageStat.Stat(ImageChops.difference(a.crop(box), b.crop(box))).mean for name,box in regions.items()}
    landing_errors = [
        max(ImageStat.Stat(ImageChops.difference(Image.open(path).convert("RGB").crop(box), b.crop(box))).mean)
        for start, _, path in samples if start >= landing_end
        for name,box in regions.items() if name.startswith("shadow") or name=="content"
    ]
    report["cases"][action] = {"meanColorError": errors, "samples": len(samples), "exportedSampleMs": [before[-1][0]-frame["startedAt"], before[-1][1]-frame["startedAt"]], "nativeAtMs": done["completedAt"]-frame["startedAt"], "maxFrameMs": done["maxFrameMs"],
                               "peakLandingColorError": max(landing_errors), "atomicHandoff": done["atomicHandoff"],
                               "durationMs": done["completedAt"]-done["startedAt"], "handoffFallback": done["handoffFallback"]}
    print(action, json.dumps(report["cases"][action]), flush=True)
    if args.artifacts:
        from PIL import ImageDraw
        args.artifacts.mkdir(parents=True, exist_ok=True)
        shown = samples[::max(1, len(samples)//7)]
        sheet = Image.new("RGB", (900, 205*len(shown)), "#182026")
        draw = ImageDraw.Draw(sheet)
        for row,(start,end,path) in enumerate(shown):
            shot = Image.open(path).convert("RGB")
            sheet.paste(shot.crop((0, 0, 900, 180)), (0, row*205+25))
            draw.text((5,row*205+5), f"{start-frame['startedAt']:.0f}-{end-frame['startedAt']:.0f} ms, native at {done['completedAt']-frame['startedAt']:.0f} ms", fill="white")
        sheet.save(args.artifacts / f"{args.backend}-{action}-normal.png")
    assert max(landing_errors) < 10, landing_errors




try:
    desktop_file.parent.mkdir(parents=True, exist_ok=True)
    desktop_file.write_text(
        "[Desktop Entry]\nType=Application\nName=Caelestia content check\nIcon=system-file-manager\n"
        f"Exec=env QT_QPA_PLATFORM={'xcb' if args.backend == 'x11' else 'wayland'} "
        f"dolphin --new-window --desktopfile {app_id} /usr/share/applications\n"
        f"StartupWMClass={'dolphin' if args.backend == 'x11' else app_id}\nStartupNotify=false\nTerminal=false\n"
    )

    def launcher_ready():
        ipc("appcentral", "refresh")
        return any(app["id"] == app_id for app in json.loads(ipc("appcentral", "list")))

    wait(launcher_ready, "The temporary Dolphin launcher was not discovered")
    if hub()["open"]:
        ipc("minimized", "toggle")
    run("hyprctl", "dispatch", 'hl.dsp.focus({workspace="918"})')
    time.sleep(0.4)
    ipc("windowdrawer", "hold", "false" if args.normal_speed else "true")
    ipc("appcentral", "favorite", app_id)
    ipc("minimized", "toggle")
    time.sleep(0.6)
    panel = hub()
    index = panel["icons"].index(app_id)
    x = panel["mini"]["x"] + 30 + 46 * (index % 12)
    y = panel["mini"]["y"] + 28 + 46 * (index // 12)
    click(x, y)
    owned = wait(lambda: next((c for c in clients() if c["class"].lower() in (app_id, "org.kde.dolphin", "dolphin") and (c["address"],c["pid"]) not in original_clients), None), "The actual app-hub click did not launch Dolphin")
    assert owned["xwayland"] == (args.backend == "x11"), owned
    with tempfile.TemporaryDirectory(prefix="central-edge-crops-") as directory:
        directory = Path(directory)
        compare_handoff("open", directory)
        if args.floating:
            selector = json.dumps("address:"+owned["address"])
            run("hyprctl", "dispatch", "function() "
                "hl.dispatch(hl.dsp.focus({window="+selector+"})); "
                "hl.dispatch(hl.dsp.window.float({action=\"enable\"})); "
                "hl.dispatch(hl.dsp.window.resize({x=960,y=640,relative=false})); "
                "hl.dispatch(hl.dsp.window.move({x=480,y=200,relative=false})); end")
            time.sleep(0.8)
            owned = next(c for c in clients() if c["address"]==owned["address"])
        ipc("minimized", "minimizeWindow", owned["address"])
        wait(lambda: any(c["address"] == owned["address"] and c["workspace"]["name"] == "special:caelestia-minimized" for c in clients()), "The fixture did not minimize")
        ipc("windowdrawer", "hold", "false" if args.normal_speed else "true")
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
    if not owned:
        owned = next((c for c in clients() if c["workspace"]["name"]=="918"
                      and c["class"].lower() in (app_id,"org.kde.dolphin","dolphin")
                      and (c["address"],c["pid"]) not in original_clients), None)
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
    (root / f"test-results/content-{args.backend}{'-normal' if args.normal_speed else ''}.json").write_text(json.dumps(report, indent=2))

assert original_clients <= {(c["address"], c["pid"]) for c in clients()}
assert {e["address"] for e in original_entries} == {e["address"] for e in json.loads(ipc("minimized", "list"))}
assert json.loads(ipc("appcentral", "info"))["favorites"] == original_favorites
report["passed"] = True
(root / f"test-results/content-{args.backend}{'-normal' if args.normal_speed else ''}.json").write_text(json.dumps(report, indent=2))
