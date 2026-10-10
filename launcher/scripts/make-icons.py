#!/usr/bin/env python3
"""Draw the launcher's own icons: the menu bar template icon (18pt, 1x/2x), the macOS app icon set,
and the 64x64 tiles for apps/bambu_progress/icon.png and apps/media_remote/icon.png. Everything here
is drawn from scratch; no third-party artwork is used."""
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
IMAGESET = ROOT / "Sources/BUSYLauncher/Assets.xcassets/MenuBarIcon.imageset"


def menubar(scale: int, active: bool = False) -> Image.Image:
    # A rounded "bar" outline with three lit pixels: reads as the BUSY Bar at 18pt.
    s = 18 * scale
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = 1 * scale
    d.rounded_rectangle([pad, 5 * scale, s - pad - 1, 13 * scale - 1], radius=2 * scale, outline=(0, 0, 0, 255), width=max(1, scale))
    for x in (5, 8.5, 12):
        cx = int(x * scale)
        d.rectangle([cx - scale, 8 * scale, cx + scale - 1, 10 * scale - 1], fill=(0, 0, 0, 255))
    if active:
        r = 2 * scale
        d.ellipse([s - 2 * r - scale, s - 2 * r - scale, s - scale - 1, s - scale - 1], fill=(0, 0, 0, 255))
    return im


def tile_icon(bitmap: list[str], color: tuple[int, int, int], accent: tuple[int, int, int] | None = None) -> Image.Image:
    """A pixel bitmap ('#' colour, 'o' accent, '.' transparent) on a dark rounded tile, 64x64."""
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, 63, 63], radius=14, fill=(24, 28, 36, 255))
    w, h = len(bitmap[0]), len(bitmap)
    cell = 48 // max(w, h)
    ox, oy = (64 - w * cell) // 2, (64 - h * cell) // 2
    for y, row in enumerate(bitmap):
        for x, ch in enumerate(row):
            fill = color if ch == "#" else accent if ch == "o" else None
            if fill:
                d.rectangle([ox + x * cell, oy + y * cell, ox + x * cell + cell - 1, oy + y * cell + cell - 1], fill=fill + (255,))
    return im


def printer_icon() -> Image.Image:
    import sys
    sys.path.insert(0, str(REPO))
    from apps.bambu_progress.icons import MARKS, DEFAULT_MARK
    return tile_icon(list(MARKS[DEFAULT_MARK]), (0x00, 0xD4, 0x55))


def media_icon() -> Image.Image:
    import sys
    sys.path.insert(0, str(REPO))
    from apps.media_remote.icons import BITMAPS
    return tile_icon(list(BITMAPS["youtube"]), (0xE8, 0xEB, 0xF0), (0x3D, 0xE0, 0x8A))


if __name__ == "__main__":
    IMAGESET.mkdir(parents=True, exist_ok=True)
    active = ROOT / "Sources/BUSYLauncher/Assets.xcassets/MenuBarIconActive.imageset"
    active.mkdir(parents=True, exist_ok=True)
    draw = menubar
    draw(1).save(IMAGESET / "menubar.png")
    draw(2).save(IMAGESET / "menubar@2x.png")
    draw(1, True).save(active / "menubar.png")
    draw(2, True).save(active / "menubar@2x.png")
    for folder in (IMAGESET, active):   # colour icons must not be rendered as templates
        cj = folder / "Contents.json"; meta = json.loads(cj.read_text())
        meta["properties"] = {"template-rendering-intent": "template"}
        cj.write_text(json.dumps(meta, indent=2))
    printer_icon().save(REPO / "apps/bambu_progress/icon.png")
    media_icon().save(REPO / "apps/media_remote/icon.png")
    print("wrote", IMAGESET, "and the app tiles")


# ---------------------------------------------------------------------------
# App icon (Finder / Launchpad / Spotlight). macOS AppIcon set: 16..512 @1x/@2x.
def app_icon(size: int = 1024) -> Image.Image:
    from PIL import ImageFilter

    S = size
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # macOS icon grid: 824px squircle centred in 1024.
    pad = int(S * 100 / 1024)
    radius = int(S * 185 / 1024)
    d.rounded_rectangle([pad, pad, S - pad - 1, S - pad - 1], radius=radius, fill=(30, 36, 48, 255))
    # subtle vertical gradient
    grad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(pad, S - pad):
        t = (y - pad) / max(1, S - 2 * pad)
        a = int(90 * (1 - t))
        gd.line([(pad, y), (S - pad - 1, y)], fill=(255, 255, 255, a))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([pad, pad, S - pad - 1, S - pad - 1], radius=radius, fill=255)
    im = Image.composite(Image.alpha_composite(im, grad), im, mask)
    d = ImageDraw.Draw(im)
    # The bar: a dark rounded slab with a black LED window.
    bw, bh = int(S * 0.70), int(S * 0.30)
    bx, by = (S - bw) // 2, (S - bh) // 2
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=int(bh * 0.28), fill=(58, 66, 84, 255))
    ix, iy = bx + int(bw * 0.06), by + int(bh * 0.18)
    iw, ih = bw - 2 * int(bw * 0.06), bh - 2 * int(bh * 0.18)
    d.rounded_rectangle([ix, iy, ix + iw, iy + ih], radius=int(ih * 0.18), fill=(8, 10, 14, 255))
    # LED grid 18 x 4 with a progress bar motif and three coloured lit pixels.
    cols, rows = 18, 4
    cell = iw / cols
    ph = ih / rows
    dot = cell * 0.62
    lit = {}
    for c in range(12):
        lit[(c, 2)] = (0x63, 0xE6, 0xBE)          # mint progress row
    for c, col in ((1, (0x63, 0xE6, 0xBE)), (2, (0x63, 0xE6, 0xBE)), (4, (0xFF, 0xBF, 0x47)), (5, (0xFF, 0xBF, 0x47)), (7, (0x50, 0x96, 0xFF)), (8, (0x50, 0x96, 0xFF))):
        lit[(c, 0)] = col
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gdr = ImageDraw.Draw(glow)
    for r in range(rows):
        for c in range(cols):
            cx = ix + cell * (c + 0.5)
            cy = iy + ph * (r + 0.5)
            box = [cx - dot / 2, cy - dot / 2, cx + dot / 2, cy + dot / 2]
            if (c, r) in lit:
                col = lit[(c, r)]
                gdr.rounded_rectangle(box, radius=dot * 0.25, fill=(*col, 255))
            else:
                d.rounded_rectangle(box, radius=dot * 0.25, fill=(26, 30, 40, 255))
    blurred = glow.filter(ImageFilter.GaussianBlur(radius=S * 0.012))
    im = Image.alpha_composite(im, blurred)
    im = Image.alpha_composite(im, glow)
    return im


def write_app_icon_set() -> None:
    import json

    iconset = ROOT / "Sources/BUSYLauncher/Assets.xcassets/AppIcon.appiconset"
    iconset.mkdir(parents=True, exist_ok=True)
    master = app_icon(1024)
    images = []
    for pt in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = pt * scale
            name = f"icon_{pt}x{pt}@{scale}x.png"
            master.resize((px, px), Image.LANCZOS).save(iconset / name)
            images.append({"filename": name, "idiom": "mac", "scale": f"{scale}x", "size": f"{pt}x{pt}"})
    (iconset / "Contents.json").write_text(json.dumps({"images": images, "info": {"author": "xcode", "version": 1}}, indent=2))
    print("wrote", iconset)


if __name__ == "__main__":
    write_app_icon_set()
