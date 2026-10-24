#!/usr/bin/env python3
"""Install the extension over an existing Caelestia installation, with backups."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


class Snapshot:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.records = {}

    def remember(self, path):
        path = Path(path)
        if str(path) in self.records:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            record = {"link": os.readlink(path)}
        elif path.is_file():
            copy = self.directory / f"{len(self.records):03d}-{path.name}"
            shutil.copy2(path, copy)
            record = {"copy": str(copy)}
        elif path.is_dir():
            copy = self.directory / f"{len(self.records):03d}-{path.name}"
            shutil.copytree(path, copy, symlinks=True)
            record = {"directory": str(copy)}
        else:
            record = {"absent": True}
        self.records[str(path)] = record
        self.save()

    def save(self):
        (self.directory / "manifest.json").write_text(json.dumps(self.records, indent=2) + "\n")

    def link(self, path, target):
        path, target = Path(path), Path(target)
        if path.is_symlink() and path.resolve() == target.resolve():
            return
        self.remember(path)
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
        self.records[str(path)]["installed_link"] = str(target)
        self.save()

    def write(self, path, text):
        path = Path(path)
        self.remember(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Replace a symlink itself; never write through to another checkout.
        if path.is_symlink():
            path.unlink()
        path.write_text(text)
        self.records[str(path)]["installed_hash"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.save()


def check():
    missing = [b for b in ("qs", "hyprctl", "c++", "pkg-config", "rg", "ffmpeg", "ffprobe", "grim", "systemctl") if not shutil.which(b)]
    if not ((shutil.which("awww") and shutil.which("awww-daemon")) or shutil.which("linux-wallpaperengine")):
        missing.append("awww + awww-daemon (local images), or linux-wallpaperengine (Workshop)")
    for module in ("PIL", "materialyoucolor", "caelestia"):
        if importlib.util.find_spec(module) is None:
            missing.append("Python module: " + module)
    headers = subprocess.run(["pkg-config", "--exists", "hyprland"], check=False).returncode if shutil.which("pkg-config") else 1
    if headers:
        missing.append("Hyprland development headers matching the running compositor")
    if missing:
        raise SystemExit("Missing dependencies:\n- " + "\n- ".join(missing))
    version = json.loads(subprocess.check_output(["hyprctl", "version", "-j"], text=True))
    if version.get("version") != "0.56.2":
        raise SystemExit("This native extension targets Hyprland 0.56.2. Port and validate it before using another release.")
    print("Dependency check passed. Caelestia Shell 2.3.0 and its C++ QML modules must already be installed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check dependencies without changing configuration")
    args = parser.parse_args()
    check()
    if args.check:
        return
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "caelestia-central"
    main_config = config / "hypr/hyprland.lua"
    if not main_config.is_file():
        raise SystemExit("An existing Hyprland Lua configuration is required.")
    subprocess.run([str(ROOT / "hypr/plugins/caelestia-minimize/build.sh")], check=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot = Snapshot(state / "backups" / stamp)
    links = {
        config / "quickshell/caelestia": ROOT / "quickshell/caelestia",
        config / "wallpaperengine": ROOT / "wallpaperengine",
        config / "hypr/plugins/caelestia-minimize": ROOT / "hypr/plugins/caelestia-minimize",
        config / "hypr/lua/caelestia-central.lua": ROOT / "hypr/lua/caelestia-central.lua",
        config / "systemd/user/wallpaperengine.service": ROOT / "wallpaperengine/wallpaperengine.service",
    }
    original = main_config.read_text()
    line = 'require("lua.caelestia-central")'
    if line in original and all(path.is_symlink() and path.resolve() == target.resolve() for path, target in links.items()):
        print("This checkout is already installed. The original configuration backup and current preferences were preserved.")
        return
    # Read configuration before making changes; malformed JSON leaves everything intact.
    shell_path, cli_path = config / "caelestia/shell.json", config / "caelestia/cli.json"
    shell = json.loads(shell_path.read_text()) if shell_path.exists() else {}
    cli = json.loads(cli_path.read_text()) if cli_path.exists() else {}
    shell.setdefault("background", {})["wallpaperEnabled"] = False
    for key in ("enableTerm", "enableHypr", "enableDiscord", "enableSpicetify", "enablePandora", "enableFuzzel", "enableBtop", "enableNvtop", "enableHtop", "enableGtk", "enableQt", "enableWarp", "enableChromium", "enableZed", "enableCava"):
        cli.setdefault("theme", {})[key] = False
    for path, target in links.items():
        snapshot.link(path, target)
    for path, value in ((shell_path, shell), (cli_path, cli)):
        snapshot.write(path, json.dumps(value, indent=4) + "\n")
    desktop = Path.home() / ".local/share/applications/wallpaperengine-picker.desktop"
    snapshot.write(desktop, '[Desktop Entry]\nType=Application\nName=Wallpapers\nComment=Choose local and Workshop wallpapers with Caelestia colors\nIcon=preferences-desktop-wallpaper\nExec="' + str(config / 'wallpaperengine/wallpaperctl') + '" ui\nTerminal=false\nCategories=Settings;DesktopSettings;\nKeywords=wallpaper;steam;theme;colors;\n')
    if line not in original:
        snapshot.write(main_config, original.rstrip() + "\n\n-- Caelestia Central\n" + line + "\n")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    state.mkdir(parents=True, exist_ok=True)
    (state / "last-backup.txt").write_text(str(snapshot.directory) + "\n")
    print(f"Installed. Backup: {snapshot.directory}")
    print("Keep this checkout in place. Log out and back in to start the shell and wallpaper service together.")
    print("Remove any previous custom central integration to avoid duplicate shortcuts or autostart hooks.")


if __name__ == "__main__":
    main()
