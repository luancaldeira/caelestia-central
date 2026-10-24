"""Read-only, cached carousel posters from real frames and scene artwork.

PKGV/TEX layouts follow the installed linux-wallpaperengine parsers. No live
renderer is started, no Workshop asset is rewritten, and palettes stay separate.
"""
import ctypes
import ctypes.util
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import struct
import subprocess
import tempfile

from PIL import Image, ImageOps

LOG = logging.getLogger("wallpaperengine.previews")
LIMIT = 128 * 1024 * 1024


class Package:
    def __init__(self, path):
        self.path = Path(path)
        self.entries = {}
        with self.path.open("rb") as f:
            def integer():
                return struct.unpack("<I", f.read(4))[0]
            def string():
                size = integer()
                if size > 4096:
                    raise ValueError("Invalid package name")
                value = f.read(size)
                if len(value) != size:
                    raise ValueError("Truncated package name")
                return value.decode("utf-8").rstrip("\0")
            if not string().startswith("PKGV"):
                raise ValueError("Unsupported package")
            count = integer()
            if count > 100000:
                raise ValueError("Invalid package count")
            for _ in range(count):
                name = string()
                offset, length = integer(), integer()
                if name.startswith("/") or ".." in Path(name).parts:
                    raise ValueError("Unsafe package member")
                self.entries[name] = (offset, length)
            self.base = f.tell()
        self.size = self.path.stat().st_size

    def read(self, name, limit=LIMIT):
        offset, size = self.entries[name]
        if size > limit or self.base + offset + size > self.size:
            raise ValueError("Invalid package range")
        with self.path.open("rb") as f:
            f.seek(self.base + offset)
            data = f.read(size)
        if len(data) != size:
            raise ValueError("Truncated package")
        return data

    def json(self, name):
        return json.loads(self.read(name, 4 * 1024 * 1024))


def texture(data):
    """Decode the first native mip; ignore animation/lower-resolution mips."""
    f = io.BytesIO(data)
    def integer():
        return struct.unpack("<I", f.read(4))[0]
    if f.read(9) != b"TEXV0005\0" or f.read(9) != b"TEXI0001\0":
        raise ValueError("Unsupported texture")
    fmt, flags, tw, th, width, height, _ = [integer() for _ in range(7)]
    container = f.read(9)
    if container not in (b"TEXB0001\0", b"TEXB0002\0", b"TEXB0003\0", b"TEXB0004\0"):
        raise ValueError("Unsupported texture container")
    if integer() < 1:
        raise ValueError("Texture has no images")
    image_format = integer() if container in (b"TEXB0003\0", b"TEXB0004\0") else 0xffffffff
    if container == b"TEXB0004\0" and integer():
        raise ValueError("Video texture")
    if not integer():
        raise ValueError("Texture has no mipmaps")
    mw, mh = integer(), integer()
    if not 0 < mw * mh <= 40_000_000 or not (0 < width <= mw and 0 < height <= mh):
        raise ValueError("Invalid texture dimensions")
    compression, unpacked = (integer(), integer()) if container != b"TEXB0001\0" else (0, 0)
    size = integer()
    if size > LIMIT or unpacked > LIMIT:
        raise ValueError("Texture too large")
    raw = f.read(size)
    if len(raw) != size:
        raise ValueError("Truncated texture")
    if compression == 1:
        lib = ctypes.CDLL(ctypes.util.find_library("lz4") or "liblz4.so.1")
        decode = lib.LZ4_decompress_safe
        decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        decode.restype = ctypes.c_int
        output = ctypes.create_string_buffer(unpacked)
        if decode(raw, output, size, unpacked) != unpacked:
            raise ValueError("Invalid compressed texture")
        raw = output.raw
    elif compression:
        raise ValueError("Unsupported compression")
    if image_format != 0xffffffff:
        image = Image.open(io.BytesIO(raw))
        image.load()
        return image.convert("RGB")
    if fmt in (4, 6, 7, 12):
        decoder, name = {4: (3, "DXT5"), 6: (2, "DXT3"), 7: (1, "DXT1"), 12: (7, "BC7")}[fmt]
        image = Image.frombytes("RGBA", (mw, mh), raw, "bcn", (decoder, name))
    elif fmt in (0, 1):
        image = Image.frombytes("RGBA" if fmt == 0 else "RGB", (mw, mh), raw)
    else:
        raise ValueError("Unsupported raw texture format")
    return image.crop((0, 0, width, height)).convert("RGB")


def scene_image(item):
    package = Package(Path(item["path"]) / "scene.pkg")
    scene = package.json("scene.json")
    candidates = []
    for obj in scene.get("objects", []):
        visible = obj.get("visible", True)
        if isinstance(visible, dict):
            visible = visible.get("value", True)
        if not visible or not isinstance(obj.get("image"), str):
            continue
        try:
            dimensions = [float(v) for v in obj.get("size", "0 0").split()]
            candidates.append((dimensions[0] * dimensions[1], obj["image"]))
        except (ValueError, AttributeError, IndexError):
            continue
    candidates.sort(reverse=True)
    # A thumbnail is preferable to an incomplete composition of similarly-sized layers.
    if not candidates or (len(candidates) > 1 and candidates[0][0] < candidates[1][0] * 4):
        raise ValueError("Scene requires its rendered composition")
    model = package.json(candidates[0][1])
    material = package.json(model["material"])
    tex = material["passes"][0]["textures"][0]
    if isinstance(tex, dict):
        tex = tex["name"]
    return texture(package.read("materials/" + tex + ".tex"))


def key(item, cache):
    render = cache / "renders" / f'{item["id"]}-{item["signature"]}.png'
    try:
        stat = render.stat()
        stamp = (stat.st_size, stat.st_mtime_ns)
    except OSError:
        stamp = None
    digest = hashlib.sha256(repr((3, item["signature"], stamp)).encode()).hexdigest()[:24]
    return cache / "posters" / digest, render if stamp else None


def cached(item, cache):
    prefix, _ = key(item, cache)
    try:
        result = json.loads(prefix.with_suffix(".json").read_text())
        if Path(result["displayPreview"]).is_file():
            return result
    except (OSError, ValueError, KeyError):
        pass
    return {"displayPreview": item.get("preview", ""), "previewSource": "original thumbnail"}


def prepare(item, cache):
    from catalog import atomic
    prefix, render = key(item, cache)
    if prefix.with_suffix(".json").is_file():
        existing = cached(item, cache)
        if existing.get("previewWidth"):
            return existing
    image, source = None, "local image" if item.get("source") == "local" else "original thumbnail"
    try:
        if render:
            with Image.open(render) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
            source = "rendered scene capture"
        elif item["type"] == "video" and item.get("file"):
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", item["file"]],
                                   capture_output=True, text=True, timeout=8, check=True)
            duration = float(json.loads(probe.stdout)["format"]["duration"])
            frame = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-threads", "2", "-ss", str(max(0, duration * .17)),
                                    "-i", item["file"], "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2",
                                    "-threads", "2", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
                                   capture_output=True, timeout=12, check=True)
            with Image.open(io.BytesIO(frame.stdout)) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
            source = "video frame"
        else:
            with Image.open(item["preview"]) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
            if item["type"] == "scene" and (image.width < 840 or image.height < 488):
                try:
                    original = scene_image(item)
                    if min(original.width / 420, original.height / 244) > min(image.width / 420, image.height / 244):
                        image, source = original, "original scene artwork"
                except (OSError, ValueError, KeyError, IndexError, TypeError, struct.error):
                    LOG.debug("No standalone scene artwork for %s", item["id"], exc_info=True)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        LOG.warning("Could not prepare native poster for %s", item["id"], exc_info=True)
    if image is None:
        return cached(item, cache)
    image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)  # Never enlarge a tiny preview.
    prefix.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=prefix.parent, suffix=".jpg")
    try:
        os.close(fd)
        image.save(temp, quality=94, subsampling=0)
        os.replace(temp, prefix.with_suffix(".jpg"))
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    result = {"displayPreview": str(prefix.with_suffix(".jpg")), "previewSource": source,
              "previewWidth": image.width, "previewHeight": image.height}
    atomic(prefix.with_suffix(".json"), result)
    return result


def login_key(item, cache, rendered=None):
    cache = Path(cache)
    if rendered is None:
        candidate = cache / "renders" / f'{item["id"]}-{item["signature"]}.png'
        rendered = candidate if candidate.is_file() else None
    stamp = None
    if rendered:
        try:
            stat = Path(rendered).stat()
            stamp = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            rendered = None
    digest = hashlib.sha256(repr((1, item["signature"], stamp)).encode()).hexdigest()[:24]
    target = cache / "login" / f'{item["id"]}-{digest}.jpg'
    return target, rendered


def cached_login_wallpaper(item, cache):
    target, _ = login_key(item, cache)
    try:
        return str(target) if target.is_file() and target.stat().st_size else None
    except OSError:
        return None


def prepare_login_wallpaper(item, cache, rendered=None):
    """Cache a display-resolution still, independent of the colour sample."""
    cache = Path(cache)
    target, rendered = login_key(item, cache, rendered)
    if target.is_file() and target.stat().st_size:
        return str(target)

    image = None
    try:
        if item.get("source") == "local":
            with Image.open(item["file"]) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
        elif rendered:
            with Image.open(rendered) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
        elif item.get("type") == "video" and item.get("file"):
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", item["file"]],
                capture_output=True, text=True, timeout=8, check=True,
            )
            duration = float(json.loads(probe.stdout)["format"]["duration"])
            frame = subprocess.run(
                ["ffmpeg", "-nostdin", "-v", "error", "-threads", "2", "-ss",
                 str(max(0, duration * .17)), "-i", item["file"], "-frames:v", "1",
                 "-vf", "scale='min(2560,iw)':-2", "-threads", "2", "-f", "image2pipe",
                 "-vcodec", "png", "pipe:1"],
                capture_output=True, timeout=20, check=True,
            )
            with Image.open(io.BytesIO(frame.stdout)) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
        elif item.get("type") == "scene":
            image = scene_image(item)
    except (OSError, ValueError, KeyError, IndexError, TypeError, struct.error, subprocess.SubprocessError):
        LOG.warning("Could not extract a high-resolution login still for %s", item["id"], exc_info=True)

    if image is None:
        result = prepare(item, cache)
        source = result.get("displayPreview") or item.get("preview")
        if not source:
            raise ValueError("No image is available for the login background.")
        # A transient decoder failure must not permanently cache a thumbnail as
        # the native video still. The next application should retry extraction.
        if item.get("type") == "video":
            return str(source)
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")

    image.thumbnail((2560, 1440), Image.Resampling.LANCZOS)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=target.parent, suffix=".jpg")
    try:
        os.close(fd)
        image.save(temp, quality=94, subsampling=0)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return str(target)
