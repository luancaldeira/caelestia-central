"""Wallpaper-only sampling and Material colour roles; no global theme commands."""
import hashlib
import json
import math
import subprocess
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageOps, ImageStat
from catalog import CACHE, STATE, atomic, load

VERSION = 2


def crop(image, aspect, width=384):
    return ImageOps.fit(ImageOps.exif_transpose(image).convert("RGB"), (width, max(1, round(width / aspect))),
                        method=Image.Resampling.LANCZOS)


def representative(item, aspect, force=False):
    key = hashlib.sha256(f'{item["signature"]}:{aspect:.4f}'.encode()).hexdigest()[:24]
    directory = CACHE / "images" / key
    directory.mkdir(parents=True, exist_ok=True)
    sample, poster = directory / "sample.png", directory / "poster.png"
    if not force and sample.exists() and poster.exists():
        return sample, poster, load(directory / "source.json", {}).get("source", "preview")
    frames = []
    if item["type"] == "video" and item["file"]:
        try:
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                    "-of", "json", item["file"]], capture_output=True, text=True, timeout=8)
            duration = float(json.loads(probe.stdout)["format"]["duration"])
            for i, fraction in enumerate((.17, .49, .81)):
                frame = directory / f"frame-{i}.png"
                subprocess.run(["ffmpeg", "-v", "error", "-threads", "2", "-ss",
                                str(max(.1, duration * fraction)), "-i", item["file"],
                                "-frames:v", "1", "-vf", "scale=768:-2", "-y", str(frame)],
                               capture_output=True, timeout=12, check=True)
                with Image.open(frame) as img:
                    img = crop(img, aspect)
                    if sum(ImageStat.Stat(img).mean) > 18:
                        frames.append(img.copy())
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            pass
    source = "video frames" if frames else "local image" if item.get("source") == "local" else "Workshop preview"
    if not frames:
        if not item["preview"]:
            raise ValueError("No usable image is available to generate this wallpaper palette.")
        with Image.open(item["preview"]) as img:
            frames = [crop(img, aspect)]
    mosaic = Image.new("RGB", (frames[0].width, frames[0].height * len(frames)))
    for i, img in enumerate(frames):
        mosaic.paste(img, (0, i * img.height))
    mosaic.save(sample)
    means = [ImageStat.Stat(img).mean for img in frames]
    average = [sum(m[i] for m in means) / len(means) for i in range(3)]
    index = min(range(len(frames)), key=lambda n: sum((means[n][i]-average[i])**2 for i in range(3)))
    frames[index].save(poster)
    atomic(directory / "source.json", {"source": source})
    return sample, poster, source


def luminance(value):
    rgb = [int(value[i:i+2], 16) / 255 for i in (0, 2, 4)]
    rgb = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in rgb]
    return sum(v*w for v, w in zip(rgb, (.2126, .7152, .0722)))


def contrast(a, b):
    a, b = sorted((luminance(a), luminance(b)))
    return (b + .05) / (a + .05)


def generate(sample, prefs, source, poster):
    from materialyoucolor.quantize import ImageQuantizeCelebi
    from materialyoucolor.hct import Hct
    from caelestia.utils.material.generator import gen_scheme

    populations = ImageQuantizeCelebi(str(sample), 1, 64)
    total = sum(populations.values()) or 1
    candidates = []
    for argb, count in populations.items():
        hct = Hct.from_int(argb)
        if 8 < hct.tone < 96:
            candidates.append((hct, count/total))
    candidates.sort(key=lambda pair: pair[1] * (1 + min(pair[0].chroma, 65)/40), reverse=True)
    if not candidates:
        candidates = [(Hct.from_int(max(populations, key=populations.get)), 1)]
    # Discard rare colourful specks; neutral scenes retain their real hue/chroma.
    meaningful = [p for p in candidates if p[1] >= .012 and p[0].chroma >= 12]
    seed = (meaningful or candidates)[0][0]
    if prefs.get("seed"):
        seed = Hct.from_int(int("ff" + prefs["seed"].lstrip("#"), 16))
    options = []
    hues = []
    for hct, weight in meaningful + candidates:
        if all(min(abs(hct.hue-h), 360-abs(hct.hue-h)) > 24 for h in hues):
            hues.append(hct.hue)
            options.append(f'{hct.to_int() & 0xffffff:06x}')
        if len(options) == 5:
            break
    if prefs.get("mode", "dark") == "auto":
        with Image.open(poster) as img:
            avg = ImageStat.Stat(img.convert("RGB")).mean
        mode = "light" if sum(avg)/3 > 175 else "dark"
    else:
        mode = prefs.get("mode", "dark")
    variant = "fidelity" if prefs.get("intensity") == "viva" else "content"
    spec = SimpleNamespace(mode=mode, variant=variant, flavour="default")
    colours = gen_scheme(spec, seed)
    # Pull secondary/tertiary towards actual additional image hues, rather than an
    # arbitrary complementary hue. Keep Material's accessible tone assignments.
    for role, option in zip(("secondary", "tertiary"), options[1:]):
        hue = Hct.from_int(int("ff"+option, 16)).hue
        for name, value in list(colours.items()):
            if name.lower().startswith(role) or name.lower().startswith("on"+role):
                hct = Hct.from_int(int("ff"+value, 16))
                hct.hue = hue
                colours[name] = f'{hct.to_int() & 0xffffff:06x}'
    for on, surface in (("onSurface", "surface"), ("onSurfaceVariant", "surfaceContainerHigh"),
                        ("onPrimary", "primary"), ("onSecondary", "secondary"),
                        ("onTertiary", "tertiary"), ("onPrimaryContainer", "primaryContainer"),
                        ("onSecondaryContainer", "secondaryContainer"), ("onTertiaryContainer", "tertiaryContainer")):
        if contrast(colours[on], colours[surface]) < 4.5:
            colours[on] = max(("ffffff", "000000"), key=lambda v: contrast(v, colours[surface]))
    return {"scheme": {"name": "dynamic", "flavour": "default", "mode": mode,
                       "variant": variant, "colours": colours},
            "swatches": options, "seed": f'{seed.to_int() & 0xffffff:06x}',
            "source": source, "poster": str(poster), "version": VERSION}


def cached_theme(item, aspect, prefs, force=False, rendered=None):
    render_signature = None
    if rendered and Path(rendered).is_file():
        stat = Path(rendered).stat()
        render_signature = [str(rendered), stat.st_size, stat.st_mtime_ns]
    key = hashlib.sha256(json.dumps([item["signature"], round(aspect, 4), prefs, VERSION, render_signature],
                                    sort_keys=True).encode()).hexdigest()[:24]
    dest = CACHE / "palettes" / f"{key}.json"
    previous = load(dest)
    if previous and not force and Path(previous["poster"]).exists():
        return previous
    if rendered and Path(rendered).is_file():
        sample = CACHE / "images" / f'render-{item["id"]}-{item["signature"]}.png'
        sample.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(rendered) as img:
            crop(img, aspect, 640).save(sample)
        poster, source = sample, "rendered scene capture"
    else:
        sample, poster, source = representative(item, aspect, force)
    result = generate(sample, prefs, source, poster)
    atomic(dest, result)
    return result


def apply_wallpaper_source(wallpaper_source):
    """Publish the display image without changing its independently sampled colours."""
    target = STATE.parent / "caelestia"
    wallpaper_source = str(wallpaper_source)
    atomic(target / "wallpaper/path.txt", wallpaper_source)
    for name in ("current", "thumbnail.jpg"):
        path = target / "wallpaper" / name
        tmp = path.with_name(name + ".wpe-tmp")
        tmp.unlink(missing_ok=True)
        tmp.symlink_to(wallpaper_source)
        tmp.replace(path)


def apply(theme, wallpaper_source=None):
    """Only the shell's state/thumbnail. Do not call Caelestia's global writers."""
    target = STATE.parent / "caelestia"
    old = load(target / "scheme.json")
    if old and old != theme["scheme"]:
        atomic(STATE / "previous-scheme.json", old)
    apply_wallpaper_source(wallpaper_source or theme["poster"])
    atomic(target / "scheme.json", theme["scheme"])
