"""Read the user's existing Steam library. Never download or install content."""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from subscriptions import subscribed
import previews

HOME = Path.home()
STATE = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / "wallpaperengine"
CACHE = Path(os.environ.get("XDG_CACHE_HOME", HOME / ".cache")) / "wallpaperengine"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "wallpaperengine"
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))


def load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def local_file(folder, value):
    """Workshop metadata is untrusted; referenced files must stay inside the item."""
    if not isinstance(value, str) or not value:
        return None
    path = (folder / value.replace("\\", "/")).resolve()
    return path if path.is_relative_to(folder.resolve()) and path.is_file() else None


def libraries():
    roots = [HOME / ".local/share/Steam", HOME / ".steam/steam", HOME / ".steam/root",
             HOME / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]
    prefs = load(CONFIG / "settings.json", {})
    roots += [Path(p).expanduser() for p in prefs.get("steam_libraries", [])]
    found = {}
    for root in roots:
        if root.is_dir():
            found[str(root.resolve())] = root.resolve()
        vdf = root / "steamapps/libraryfolders.vdf"
        if vdf.is_file():
            for value in re.findall(r'"path"\s+"((?:\\.|[^"\\])*)"', vdf.read_text(errors="replace")):
                p = Path(value.replace("\\\\", "\\").replace('\\"', '"')).expanduser()
                if p.is_dir():
                    found[str(p.resolve())] = p.resolve()
    return list(found.values())


def scan():
    items = {}
    roots = libraries()
    assets = ""
    subscription_ids, watch = subscribed(roots, CACHE)
    for lib in roots:
        app = lib / "steamapps/common/wallpaper_engine/assets"
        if app.is_dir():
            assets = str(app)
        root = lib / "steamapps/workshop/content/431960"
        if not root.is_dir():
            continue
        watch.append(str(root))
        for folder in sorted(root.iterdir()):
            if not folder.is_dir() or not folder.name.isdigit():
                continue
            if subscription_ids is not None and folder.name not in subscription_ids:
                continue
            watch.append(str(folder))
            data = load(folder / "project.json", {}) or {}
            if not isinstance(data, dict):
                data = {}
            kind = str(data.get("type", "unknown")).lower()
            content = local_file(folder, data.get("file"))
            preview = local_file(folder, data.get("preview"))
            if not preview:
                preview = next((local_file(folder, p.name) for p in folder.glob("preview.*") if p.suffix.lower() in
                                (".jpg", ".jpeg", ".png", ".webp", ".gif") and local_file(folder, p.name)), None)
            missing = not content and not (kind == "scene" and (folder / "scene.pkg").is_file())
            signature = [str(folder.resolve())]
            for p in (folder / "project.json", content, preview, folder / "scene.pkg"):
                try:
                    if p and p.is_file():
                        s = p.stat()
                        signature += [p.name, s.st_size, s.st_mtime_ns]
                except OSError:
                    pass  # Steam may replace files while a Workshop download finishes.
            item = {"id": folder.name, "title": str(data.get("title") or folder.name),
                    "type": kind, "path": str(folder.resolve()), "file": str(content or ""),
                    "preview": str(preview or ""), "missing": missing,
                    "signature": hashlib.sha256(repr(signature).encode()).hexdigest()[:20]}
            item.update(previews.cached(item, CACHE))
            if folder.name not in items or (items[folder.name]["missing"] and not missing):
                items[folder.name] = item
    result = {"items": sorted(items.values(), key=lambda x: x["title"].casefold()),
              "assets": assets, "libraries": [str(p) for p in roots], "watch": sorted(set(watch)),
              "subscriptionSync": subscription_ids is not None}
    atomic(CACHE / "catalog.json", result)
    return result
