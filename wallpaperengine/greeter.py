"""Optional public wallpaper export, performed only with the desktop user's rights."""
import json
import os
from pathlib import Path
import tempfile


def write(path, data, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".central-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def configure(config_home, directory):
    """Preserve other settings; this function must run as the desktop user."""
    path = Path(config_home) / "wallpaperengine/settings.json"
    settings = json.loads(path.read_text()) if path.exists() else {}
    settings.setdefault("greeter", {})["export_directory"] = str(directory)
    write(path, (json.dumps(settings, indent=2) + "\n").encode(), mode=0o600)
    return settings


def export(source, scheme, settings):
    directory = (settings or {}).get("greeter", {}).get("export_directory")
    if not directory:
        return
    directory = Path(directory).expanduser()
    if not directory.is_absolute():
        raise ValueError("greeter.export_directory must be an absolute path.")
    # A stable, extensionless image URL lets the greeter autodetect JPEG, PNG or
    # a fallback preview without retaining a deleted/old per-wallpaper cache URL.
    write(directory / "wallpaper", Path(source).read_bytes())
    if scheme:
        write(directory / "scheme.json", (json.dumps(scheme) + "\n").encode())
