"""Full-screen notice backdrops in the style of the bar's own status screens.

Each notice (done / pause / error) is a looping 72x16 animation: a flowing two-tone gradient of the
status colour with drifting sparkles, and on the left a mark that draws itself in, shines, and fades
before the loop restarts. The big word / printer name is a device text element drawn on top (see
render.render_notice), so the frames here never contain text.
"""
from __future__ import annotations

import math
import random
from collections.abc import Callable

from .anim import LAYOUT_BGR888, bgra, encode_anim

W, H = 72, 16
FPS = 24
FRAMES = 72                      # 3 s loop
MARK_IN_END = 12                 # the mark finishes drawing itself at this frame
MARK_OUT_START = FRAMES - 8      # ...and fades over the last 8 frames

# (deep, mid, bright) per theme: background base, wave crest, sparkle / mark glow
THEMES: dict[str, tuple[str, str, str]] = {
    "done": ("#063A1F", "#118F48", "#3DE08A"),
    "pause": ("#3F2A00", "#B37400", "#FFD23F"),
    "error": ("#400A0A", "#B02222", "#FF6B6B"),
}
MARK_X, MARK_Y = 6, 0            # the marks occupy rows 2-11: optically centred, a touch above the word's rows 3-12
OUTLINE = "#031A0E"


def _rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(a: tuple[float, float, float], b: tuple[float, float, float], t: float) -> tuple[float, float, float]:
    t = max(0.0, min(1.0, t))
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t


def _backdrop(theme: tuple[str, str, str], f: int, sparkles: list[tuple[int, int, int, int]]) -> list[list[tuple[float, float, float]]]:
    """The whole screen is a gradient of the theme colour (deep -> mid -> bright -> mid -> deep) that
    sweeps from left to right, slightly tilted, with a slower second band for depth and twinkling
    sparkles. Every term is periodic in f over FRAMES, so the loop is seamless."""
    deep, mid, bright = (_rgb(c) for c in theme)
    ph = 2 * math.pi * f / FRAMES
    px = [[deep] * W for _ in range(H)]
    for y in range(H):
        for x in range(W):
            u = 2 * math.pi * x / W
            tilt = 2 * math.pi * y / (H * 3.0)                       # bands lean a little
            g1 = 0.5 + 0.5 * math.cos(u - ph - tilt)                 # one band wide as the screen, moving right
            g2 = 0.5 + 0.5 * math.cos(2 * u - 2 * ph + tilt + 1.1)   # a narrower band, same direction, slower sweep
            glow = min(1.0, 0.18 + 0.62 * g1 + 0.3 * g2 * g1)
            col = _mix(deep, mid, glow / 0.8) if glow < 0.8 else _mix(mid, bright, (glow - 0.8) / 0.2)
            px[y][x] = col
    for sx, sy, start, life in sparkles:
        age = (f - start) % FRAMES
        if age < life:
            a = math.sin(math.pi * age / life)          # fade in, fade out
            px[sy][sx] = _mix(px[sy][sx], bright, 0.9 * a)
    return px


def _check(f: int) -> dict[tuple[int, int], float]:
    """The tick, drawn as a short down stroke then a long up stroke; value = ink (0..1) per pixel."""
    path = [(1, 6), (2, 7), (3, 8), (4, 9), (5, 10), (6, 9), (7, 8), (8, 7), (9, 6), (10, 5), (11, 4), (12, 3), (13, 2)]
    return _stroke(path, f, thick=2)


def _pause(f: int) -> dict[tuple[int, int], float]:
    bars = [(x, y) for y in range(2, 12) for x in (2, 3, 4)] + [(x, y) for y in range(2, 12) for x in (8, 9, 10)]
    return _grow(bars, f)


def _cross(f: int) -> dict[tuple[int, int], float]:
    a = [(i, i) for i in range(2, 11)]          # 10 rows tall like the tick, not 12
    b = [(i, 12 - i) for i in range(2, 11)]
    return _stroke(a, f, thick=2) | _stroke(b, max(0, f - 4), thick=2)


def _stroke(path: list[tuple[int, int]], f: int, thick: int) -> dict[tuple[int, int], float]:
    n = len(path)
    progress = min(1.0, f / MARK_IN_END) if f < MARK_IN_END else 1.0
    shown = path[: max(1, round(n * progress))] if f >= 0 else []
    ink: dict[tuple[int, int], float] = {}
    for x, y in shown:
        for dx in range(thick):
            for dy in range(thick):
                ink[(x + dx, y + dy)] = 1.0
    return ink


def _grow(pixels: list[tuple[int, int]], f: int) -> dict[tuple[int, int], float]:
    progress = min(1.0, f / MARK_IN_END)
    cy = 7
    return {(x, y): 1.0 for x, y in pixels if abs(y - cy) <= progress * 6}


MARKS: dict[str, Callable[[int], dict[tuple[int, int], float]]] = {"done": _check, "pause": _pause, "error": _cross}


def bezel_lit(x: int, y: int) -> bool:
    """The outline the bar's own full-screen effects use (measured from indicator_busy_72x16): the
    first and last columns stay dark, and the top and bottom rows also skip their second pixel."""
    if x in (0, W - 1):
        return False
    if x in (1, W - 2) and y in (0, H - 1):
        return False
    return True


BEZEL_DARK = [(x, y) for y in range(H) for x in range(W) if not bezel_lit(x, y)]

# The native screens draw a one-pixel rim just inside that outline, and it is not a fixed colour:
# each rim pixel is its inner neighbour lightened toward white (measured on the firmware animations,
# rim ≈ neighbour + lift with correlation 0.9-1.0), so the rim follows whatever moves underneath.
# Top edge: about half way to white; sides: a third; bottom: a touch. The corner pixels are the
# adjacent rim pixel dimmed (0.4 at the top, 0.3 at the bottom), which rounds the corners off.
RIM_TOP, RIM_SIDE, RIM_BOTTOM = 0.5, 0.3, 0.15
CORNER_TOP, CORNER_BOTTOM = 0.4, 0.3
WHITE = (255.0, 255.0, 255.0)


def _scale(p: tuple[float, float, float], k: float) -> tuple[float, float, float]:
    return p[0] * k, p[1] * k, p[2] * k


def _rim(px: list[list[tuple[float, float, float]]]) -> None:
    """Glossy pill: the top half a little brighter than the bottom, then the rim from the neighbours."""
    for y in range(H):
        gloss = 1.18 - 0.36 * y / (H - 1)
        px[y] = [(min(255.0, r * gloss), min(255.0, g * gloss), min(255.0, b * gloss)) for r, g, b in px[y]]
    for x in range(3, W - 3):
        px[0][x] = _mix(px[1][x], WHITE, RIM_TOP)
        px[H - 1][x] = _mix(px[H - 2][x], WHITE, RIM_BOTTOM)
    for y in range(2, H - 2):
        px[y][1] = _mix(px[y][2], WHITE, RIM_SIDE)
        px[y][W - 2] = _mix(px[y][W - 3], WHITE, RIM_SIDE)
    for xl, xr in ((2, W - 3),):                          # the pixels where the top/bottom rim turns the corner
        px[1][xl] = _mix(px[1][3], WHITE, RIM_SIDE + 0.1)
        px[1][xr] = _mix(px[1][W - 4], WHITE, RIM_SIDE + 0.1)
        px[H - 2][xl] = _mix(px[H - 2][3], WHITE, RIM_BOTTOM + 0.05)
        px[H - 2][xr] = _mix(px[H - 2][W - 4], WHITE, RIM_BOTTOM + 0.05)
    for xa, xb in ((2, 3), (W - 3, W - 4)):               # anti-aliased corner pixels: dimmed copies of the rim next to them
        px[0][xa] = _scale(px[0][xb], CORNER_TOP)
        px[H - 1][xa] = _scale(px[H - 1][xb], CORNER_BOTTOM)
    for xa, xb in ((1, 2), (W - 2, W - 3)):
        px[1][xa] = _scale(px[1][xb], CORNER_TOP)
        px[H - 2][xa] = _scale(px[H - 2][xb], CORNER_BOTTOM)


def notice_frames(kind: str) -> list[bytes]:
    theme = THEMES[kind]
    mark = MARKS[kind]
    rng = random.Random(hash(kind) & 0xFFFF)
    sparkles = [(rng.randrange(W), rng.randrange(H), rng.randrange(FRAMES), rng.randrange(10, 24)) for _ in range(26)]
    outline = _rgb(OUTLINE)
    white = (255.0, 255.0, 255.0)
    bright = _rgb(theme[2])
    frames = []
    for f in range(FRAMES):
        px = _backdrop(theme, f, sparkles)
        _rim(px)
        ink = mark(f)
        fade = 1.0 if f < MARK_OUT_START else 1 - (f - MARK_OUT_START + 1) / (FRAMES - MARK_OUT_START)
        shine = 0.5 + 0.5 * math.sin(2 * math.pi * (f - MARK_IN_END) / 20) if f >= MARK_IN_END else 0.0
        if ink:
            # 1px dark outline around the mark so it reads on the bright crests
            for (x, y) in list(ink):
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        xx, yy = MARK_X + x + dx, MARK_Y + y + dy
                        if 0 <= xx < W and 0 <= yy < H and (x + dx, y + dy) not in ink:
                            px[yy][xx] = _mix(px[yy][xx], outline, 0.85 * fade)
            for (x, y), v in ink.items():
                xx, yy = MARK_X + x, MARK_Y + y
                if 0 <= xx < W and 0 <= yy < H:
                    col = _mix(white, bright, 0.35 * shine)
                    px[yy][xx] = _mix(px[yy][xx], col, v * fade)
        for x, y in BEZEL_DARK:
            px[y][x] = (0.0, 0.0, 0.0)
        raw = bytearray()
        for row in px:
            for r, g, b in row:
                raw += bytes((int(b), int(g), int(r)))
        frames.append(bytes(raw))
    return frames


def notice_animation(kind: str) -> bytes:
    return encode_anim(W, H, FPS, [(f, 1) for f in notice_frames(kind)], layout=LAYOUT_BGR888)


# --- Detail screen: the same flowing backdrop, much darker, with no mark (text sits on it) --------
DETAIL_FPS = 16
DETAIL_FRAMES = 48               # 3 s loop
DETAIL_THEMES: dict[str, tuple[str, str, str]] = {
    "run": ("#02140A", "#0A4A26", "#13803E"),
    "done": ("#02140A", "#0A4A26", "#13803E"),
    "pause": ("#1A1000", "#4A3000", "#8A5A00"),
    "error": ("#1A0404", "#4A1010", "#8A1C1C"),
    "idle": ("#0A0C12", "#1E2430", "#303A4C"),
}


def detail_frames(kind: str) -> list[bytes]:
    theme = DETAIL_THEMES[kind]
    rng = random.Random(hash(kind) & 0xFFFF)
    sparkles = [(rng.randrange(W), rng.randrange(H), rng.randrange(DETAIL_FRAMES), rng.randrange(8, 16)) for _ in range(10)]
    frames = []
    for f in range(DETAIL_FRAMES):
        px = _backdrop(theme, int(f * FRAMES / DETAIL_FRAMES), sparkles)   # same phase sweep as the notice, 3 s loop
        _rim(px)
        for x, y in BEZEL_DARK:
            px[y][x] = (0.0, 0.0, 0.0)
        raw = bytearray()
        for row in px:
            for r, g, b in row:
                raw += bytes((int(b), int(g), int(r)))
        frames.append(bytes(raw))
    return frames


def detail_animation(kind: str) -> bytes:
    return encode_anim(W, H, DETAIL_FPS, [(f, 1) for f in detail_frames(kind)], layout=LAYOUT_BGR888)


# --- Entering a printer: a ripple from the centre and a soft flash over the new screen -------------
ENTER_FPS = 24
ENTER_FRAMES = 12                # 0.5 s, played once
ENTER_SECONDS = ENTER_FRAMES / ENTER_FPS + 0.15   # plus the player's start lag


def enter_frames() -> list[bytes]:
    cx, cy = W / 2 - 0.5, H / 2 - 0.5
    frames = []
    for f in range(ENTER_FRAMES):
        t = f / (ENTER_FRAMES - 1)
        radius = 1.5 + t * 44.0                              # reaches the corners by the end
        ring_alpha = 0.95 * (1 - t) ** 1.2
        flash = max(0.0, 0.55 - 1.6 * t)                     # a quick white flash in the first frames
        px: list[tuple[int, int, int, int]] = []
        for y in range(H):
            for x in range(W):
                d = math.hypot((x - cx) / 1.0, (y - cy) * 2.2)   # the bar is wide: squash the ring vertically
                ring = max(0.0, 1 - abs(d - radius) / 2.5)
                a = min(1.0, ring * ring_alpha + flash)
                px.append((255, 255, 255, int(255 * a)) if a > 0.02 else (0, 0, 0, 0))
        frames.append(bgra(px))
    return frames


def enter_animation() -> bytes:
    return encode_anim(W, H, ENTER_FPS, [(f, 1) for f in enter_frames()])
