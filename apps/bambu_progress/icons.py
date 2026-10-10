"""8x8 pixel-art icons, encoded to PNG without Pillow, uploaded once per bar."""
from __future__ import annotations

import functools
import hashlib
import logging
import math
import struct
import zlib
from collections.abc import Sequence
from typing import Any

from .anim import bgra, encode_anim
from .config import PrinterConfig

log = logging.getLogger(__name__)

APP = "bambu-progress"
UPLOADS_ROOT = "/ext/user_assets"

# --- Palette -----------------------------------------------------------------
WHITE = "#FFFFFF"
TEXT_GREY = "#A8B2C3"
DIM = "#495365"
TRACK = "#2A3140"
GREEN = "#3DDC84"
YELLOW = "#FFD23F"
RED = "#FF4D4D"
DARK_RED = "#7A1F1F"
LIME = "#8CFE0C"
INK = "#1A1A1A"
DOT = WHITE  # the climbing dot in the "printing" logo frames

# --- Bitmaps (8 rows x 8 cols; '#' main colour, 'o' dot colour, '.' transparent) ---
# The printer mark is 7 wide x 8 tall with a vertical channel in column 3 (SLIT_X): the "printing"
# animation runs a dot down that channel. Two marks are available, chosen with `[display] mark`:
MARKS: dict[str, tuple[str, ...]] = {
    # "printer" (default): an extruder seen from the front, filament channel down the middle.
    "printer": (
        "###.###",
        "###.###",
        "###.###",
        "###.###",
        ".##.##.",
        "..#.#..",
        "..#.#..",
        "...#...",
    ),
    # "bambu": a hand-drawn rendition of the Bambu Lab mark (two blocks split by offset diagonals).
    # It is Bambu Lab's trademark: fine on your own desk, not something to ship as a default.
    "bambu": (
        "###.###",
        "###.###",
        "###..##",
        "###.#.#",
        "##..##.",
        "#.#.###",
        ".##.###",
        "###.###",
    ),
}
DEFAULT_MARK = "printer"
BITMAPS: dict[str, tuple[str, ...]] = {
    "logo": MARKS[DEFAULT_MARK],
    "check": (
        "........",
        ".......#",
        "......##",
        ".....##.",
        "#...##..",
        "##.##...",
        ".###....",
        "..#.....",
    ),
    "pause": (
        "........",
        ".##..##.",
        ".##..##.",
        ".##..##.",
        ".##..##.",
        ".##..##.",
        ".##..##.",
        "........",
    ),
    "error": (
        "#......#",
        "##....##",
        ".##..##.",
        "..####..",
        "..####..",
        ".##..##.",
        "##....##",
        "#......#",
    ),
    "hourglass": (
        "########",
        ".#....#.",
        "..#..#..",
        "...##...",
        "...##...",
        "..#..#..",
        ".#....#.",
        "########",
    ),
}


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def _rgb(color_hex: str) -> tuple[int, int, int]:
    h = color_hex.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def to_png(bitmap: Sequence[str], colors: str | dict[str, str]) -> bytes:
    """Encode a bitmap as RGBA PNG. `colors` is one hex for '#', or a char -> hex map."""
    palette = {"#": colors} if isinstance(colors, str) else colors
    rgb = {ch: _rgb(hex6) for ch, hex6 in palette.items()}
    height = len(bitmap)
    width = len(bitmap[0])
    raw = bytearray()
    for row in bitmap:
        raw.append(0)  # filter type: none
        for ch in row:
            raw += bytes((*rgb[ch], 0xFF)) if ch in rgb else b"\x00\x00\x00\x00"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


# The 2x2 grid gives each row 7 pixels for the mark: same drawing minus its top row (rows 0 and 1
# are identical, so nothing visible is lost).
SLIT_X = 3   # the vertical channel in the mark; the "printing" dot runs down it


def _scale2(rows: tuple[str, ...]) -> tuple[str, ...]:
    """Each pixel becomes a 2x2 block: the 7x7 grid mark as the 14x14 mark of the detail screen."""
    out: list[str] = []
    for r in rows:
        doubled = "".join(ch * 2 for ch in r)
        out += [doubled, doubled]
    return tuple(out)


def select_mark(name: str) -> None:
    """Install one of MARKS as the logo (8-row list mark, 7-row grid mark, 14x14 detail mark)."""
    if name not in MARKS:
        raise KeyError(name)
    BITMAPS["logo"] = MARKS[name]
    BITMAPS["grid_logo"] = MARKS[name][1:]          # rows 0 and 1 are identical in both marks: nothing visible is lost
    BITMAPS["big_logo"] = _scale2(BITMAPS["grid_logo"])
    animation_bytes.cache_clear()




def _upscale2(frame: bytes, width: int, height: int, bpp: int = 4) -> bytes:
    """Nearest-neighbour 2x of a packed frame (the animations of the 7x7 mark, blown up to 14x14)."""
    rows = [frame[y * width * bpp:(y + 1) * width * bpp] for y in range(height)]
    out = bytearray()
    for row in rows:
        doubled = b"".join(row[x * bpp:(x + 1) * bpp] * 2 for x in range(width))
        out += doubled + doubled
    return bytes(out)



def _bitmap_tag(name: str) -> str:
    """Four hex chars of the bitmap's content: a changed drawing gets a new filename, so the bar
    cannot keep serving a stale PNG that happened to have the same size."""
    return hashlib.sha1("\n".join(BITMAPS[name]).encode()).hexdigest()[:4]


def icon_filename(name: str, color_hex: str) -> str:
    return f"{name}_{color_hex.lstrip('#').lower()}_{_bitmap_tag(name)}.png"


# --- Animations: the bar plays these itself (see anim.py), so they run at their own frame rate ------
RUN_FPS = 8          # the dot moves one row per frame
RUN_HOLD = 4         # frames the dot rests at the bottom before the next one starts (0.5 s)
PULSE_FPS = 24
PULSE_FRAMES = 24    # one breath per second
TRAIL_ALPHA = 0x60   # the dot leaves a half-bright pixel behind it


def _rgba(hex6: str, alpha: int = 0xFF) -> tuple[int, int, int, int]:
    return (*_rgb(hex6), alpha)


def _blend(a: str, b: str, t: float) -> str:
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return "#%02X%02X%02X" % (round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t))


def _solid(bitmap: Sequence[str], color: str, extra: dict[tuple[int, int], tuple[int, int, int, int]] | None = None) -> bytes:
    extra = extra or {}
    return bgra([
        extra.get((x, y), _rgba(color) if ch == "#" else _rgba(WHITE) if ch == "o" else (0, 0, 0, 0))
        for y, row in enumerate(bitmap) for x, ch in enumerate(row)
    ])


def run_frames(bitmap: Sequence[str], color: str) -> list[bytes]:
    """Printing: a white dot runs down the slit from the top row to the bottom, like filament leaving
    the nozzle, trailing a dim pixel above it. The player holds the last frame (RUN_HOLD) before looping."""
    frames = []
    for y in range(len(bitmap)):
        extra = {(SLIT_X, y): _rgba(DOT)}
        if y > 0:
            extra[(SLIT_X, y - 1)] = _rgba(DOT, TRAIL_ALPHA)
        frames.append(_solid(bitmap, color, extra))
    return frames


def pulse_frames(bitmap: Sequence[str], color_a: str, color_b: str, steps: int = PULSE_FRAMES) -> list[bytes]:
    """Breathing between two colours (cosine ease, so the loop is seamless)."""
    return [_solid(bitmap, _blend(color_a, color_b, (1 - math.cos(2 * math.pi * i / steps)) / 2)) for i in range(steps)]


ANIMATIONS = ("logo_run", "logo_error")   # each also exists as grid_<name> (7-row mark); finished is a static green mark

@functools.lru_cache(maxsize=None)
def animation_bytes(name: str, color: str) -> bytes:
    """`.anim` for one logo animation in one colour. The error pulse ignores `color`'s role as
    accent (always red/dark red); `color` just keys the filename."""
    if name.startswith("notice_"):
        from .fx import notice_animation          # late import: fx is heavier than the icon bitmaps
        return notice_animation(name[len("notice_"):])
    if name.startswith("detail_"):
        from .fx import detail_animation
        return detail_animation(name[len("detail_"):])
    if name == "enter":
        from .fx import enter_animation
        return enter_animation()
    grid = name.startswith("grid_")
    big = name.startswith("big_")
    kind = name[5:] if grid else name[4:] if big else name
    bitmap = BITMAPS["grid_logo" if (grid or big) else "logo"]
    if kind == "logo_run":
        frames = run_frames(bitmap, color)
        holds = [1] * len(frames)
        holds[-1] = RUN_HOLD
        fps = RUN_FPS
    elif kind == "logo_error":
        frames, fps = pulse_frames(bitmap, RED, DARK_RED), PULSE_FPS
        holds = [1] * len(frames)
    else:
        raise KeyError(name)
    w, h = len(bitmap[0]), len(bitmap)
    if big:                                    # the 7x7 frames blown up to 14x14 for the detail screen
        frames = [_upscale2(f, w, h) for f in frames]
        w, h = 2 * w, 2 * h
    return encode_anim(w, h, fps, list(zip(frames, holds)))


def anim_filename(name: str, color_hex: str) -> str:
    tag = hashlib.sha1(animation_bytes(name, color_hex)).hexdigest()[:4]
    return f"{name}_{color_hex.lstrip('#').lower()}_{tag}.anim"


def required_animations(configs: Sequence[PrinterConfig]) -> dict[str, bytes]:
    wanted = {("logo_run", cfg.color) for cfg in configs} | {("logo_error", RED)}
    wanted |= {(f"grid_{n}", c) for n, c in wanted} | {(f"big_{n}", c) for n, c in wanted}
    wanted |= {("notice_done", GREEN), ("notice_pause", YELLOW), ("notice_error", RED)}
    wanted |= {("detail_run", GREEN), ("detail_done", GREEN), ("detail_pause", YELLOW), ("detail_error", RED), ("detail_idle", DIM), ("enter", WHITE)}
    return {anim_filename(n, c): animation_bytes(n, c) for n, c in sorted(wanted)}


def required_icons(configs: Sequence[PrinterConfig]) -> dict[str, bytes]:
    wanted: set[tuple[str, str]] = {("logo", cfg.color) for cfg in configs}
    wanted.update({
        ("logo", DIM), ("logo", GREEN), ("logo", YELLOW), ("logo", RED),
    })
    wanted.update({(f"grid_{n}", c) for n, c in list(wanted)})   # 7-row copies for the grid
    wanted.update({(f"big_{n}", c) for n, c in list(wanted) if n == "logo"})   # 14x14 copies for the detail screen
    wanted.update({
        ("hourglass", DIM),
        ("check", GREEN), ("pause", YELLOW), ("error", RED),
    })
    return {icon_filename(n, c): to_png(BITMAPS[n], {"#": c, "o": DOT}) for n, c in sorted(wanted)}


async def ensure_uploaded(bar: Any, icons: dict[str, bytes], *, application_name: str = APP) -> list[str]:
    """Upload icons that are missing or have a different size on the bar."""
    remote_sizes: dict[str, int] = {}
    try:
        listing = await bar.storage_list(f"{UPLOADS_ROOT}/{application_name}")
        for entry in listing.list:
            size = getattr(entry, "size", None)
            if size is not None:
                remote_sizes[entry.name] = size
    except Exception as exc:  # noqa: BLE001 - listing is an optimisation only
        log.debug("asset listing failed, uploading everything: %s", exc)
    stale = [n for n in remote_sizes if n.endswith((".png", ".anim")) and n not in icons and not n.startswith("thumb_")]
    if stale:
        # Old bitmap versions linger otherwise; the bar has no per-file delete, so wipe and re-upload.
        try:
            await bar.assets_delete(application_name)
            remote_sizes = {}
            log.info("removed %d stale icon file(s) from the bar", len(stale))
        except Exception as exc:  # noqa: BLE001
            log.debug("asset wipe failed: %s", exc)
    uploaded: list[str] = []
    for filename, data in icons.items():
        if remote_sizes.get(filename) == len(data):
            continue
        await bar.assets_upload(application_name, filename, data)
        uploaded.append(filename)
    return uploaded


select_mark(DEFAULT_MARK)
