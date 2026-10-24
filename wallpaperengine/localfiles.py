"""Read selected image folders without modifying their contents."""
import hashlib
import os
from pathlib import Path

from PIL import Image, UnidentifiedImageError

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def scan(folders, cache):
    import previews
    items, watch, sources = {}, set(), []
    cache_root = Path(cache).resolve()
    for value in folders:
        root = Path(value).expanduser().resolve()
        available = root.is_dir() and os.access(root, os.R_OK | os.X_OK)
        sources.append({"path": str(root), "available": available})
        parent = root
        while not parent.is_dir() and parent != parent.parent:
            parent = parent.parent
        watch.add(str(parent))
        if not available:
            continue
        for directory, dirs, files in os.walk(root, followlinks=False):
            # Importing a parent of our cache must not feed generated posters
            # back into the source library indefinitely.
            if Path(directory).is_relative_to(cache_root):
                dirs[:] = []
                continue
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(directory) / d).is_symlink()
                             and not (Path(directory) / d).is_relative_to(cache_root))
            watch.add(directory)
            for name in sorted(files):
                path = Path(directory) / name
                if name.startswith(".") or path.suffix.lower() not in EXTENSIONS:
                    continue
                try:
                    path = path.resolve()
                    if not path.is_relative_to(root):
                        continue
                    stat = path.stat()
                    with Image.open(path) as image:
                        if image.format not in {"JPEG", "PNG", "WEBP", "BMP", "GIF"}:
                            continue
                    ident = "local-" + hashlib.sha256(os.fsencode(path)).hexdigest()[:24]
                    signature = hashlib.sha256(repr((str(path), stat.st_size, stat.st_mtime_ns)).encode()).hexdigest()[:20]
                    item = {"id": ident, "title": path.stem, "type": "image", "source": "local",
                            "folder": str(root), "path": str(path.parent), "file": str(path),
                            "preview": str(path), "signature": signature, "missing": False}
                    item.update(previews.cached(item, cache))
                    items.setdefault(ident, item)
                except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
                    continue  # Files can disappear or be incomplete during a copy.
    return list(items.values()), watch, sources
