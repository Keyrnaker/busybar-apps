"""72x16 layout: [app icon 8x8][thumb 21x16] title / time / progress bar. Pure functions."""
from __future__ import annotations

from busylib import types

from apps.bambu_progress.icons import DIM, TEXT_GREY, TRACK, WHITE
from apps.bambu_progress.render import rgba

from .icons import KIND_COLORS, PLACEHOLDER, icon_filename
from .nowplaying import NowPlaying

APP = "media-remote"
PRIORITY = 50
TEXT_X = 31
TEXT_W = 72 - TEXT_X          # 41px
SCROLL_AFTER = 8              # small font: ~5px per glyph
SCROLL_AFTER_GLOBAL = 4       # global font (the only one with Hangul/CJK): ~10px per glyph
SCROLL_RATE = 20
GLOBAL_Y = 7                  # mid anchor for the 12px global font: rows 1..12 stay on the 16px screen


def format_time(seconds: float) -> str:
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def _text(id: str, x: int, y: int, text: str, font: str, color: str, **extra) -> types.TextElement:
    return types.TextElement(id=id, x=x, y=y, text=text, font=font, color=color, align="mid_left", **extra)


def _rect(id: str, x: int, y: int, w: int, h: int, color: str) -> types.RectangleElement:
    return types.RectangleElement(id=id, x=x, y=y, width=w, height=h, fill="solid", fill_colors=[color], border_width=0)


def needs_global_font(text: str) -> bool:
    """Only the 'global' device font has glyphs outside ASCII (Hangul, CJK, accents)."""
    return any(ord(ch) > 127 for ch in text)


def _title(text: str, color: str) -> types.TextElement:
    if needs_global_font(text):
        extra = {"width": TEXT_W, "scroll_rate": SCROLL_RATE} if len(text) > SCROLL_AFTER_GLOBAL else {}
        return _text("3", TEXT_X, GLOBAL_Y, text, "global", color, **extra)
    extra = {"width": TEXT_W, "scroll_rate": SCROLL_RATE} if len(text) > SCROLL_AFTER else {}
    return _text("3", TEXT_X, 3, text or "-", "small", color, **extra)


def render(np: NowPlaying, kind: str, thumb_name: str | None, pos: float, preview: str | None, frame: int) -> types.DisplayElements:
    color = KIND_COLORS.get(kind, WHITE)
    tall = needs_global_font(np.title)   # 12px font: title takes the whole text area, no time line
    elements: list = [
        types.ImageElement(id="1", x=0, y=4, path=icon_filename(kind)),
        types.ImageElement(id="2", x=9, y=0, path=thumb_name) if thumb_name else types.ImageElement(id="2", x=13, y=2, path=PLACEHOLDER),
    ]
    if preview and tall:
        elements.append(_text("4", TEXT_X, GLOBAL_Y, preview, "small", rgba(color)))
    else:
        elements.append(_title(np.title, rgba(WHITE if np.playing else TEXT_GREY)))
        if preview:
            elements.append(_text("4", TEXT_X, 10, preview, "tiny", rgba(color)))
        elif not tall:
            elements.append(_text("4", TEXT_X, 10, f"{format_time(pos)}/{format_time(np.duration)}", "tiny", rgba(TEXT_GREY)))
    elements.append(_rect("5", TEXT_X, 14, TEXT_W, 2, rgba(TRACK)))
    if np.duration > 0:
        w = round(TEXT_W * max(0.0, min(1.0, pos / np.duration)))
        if w > 0:
            elements.append(_rect("6", TEXT_X, 14, w, 2, rgba(color, 0xFF if np.playing else 0x60)))
    return types.DisplayElements(application_name=APP, priority=PRIORITY, elements=elements)


def render_idle(frame: int) -> types.DisplayElements:
    elements = [
        types.ImageElement(id="1", x=0, y=4, path=icon_filename("generic", dim=True)),
        types.ImageElement(id="2", x=13, y=2, path=PLACEHOLDER),
        _text("3", TEXT_X, 7, "재생 중인 미디어 없음", "global", rgba(DIM), width=TEXT_W, scroll_rate=SCROLL_RATE),
    ]
    return types.DisplayElements(application_name=APP, priority=PRIORITY, elements=elements)


# --- Apple Music mode: two pages that alternate (title/artist, then big time + thick bar) ---------
MUSIC_PAGE_TICKS = (8, 6)          # render ticks (0.5 s) per page: 4 s of title, 3 s of time


def music_page(frame: int, has_lyrics: bool = False) -> int:
    """Without lyrics the title and time pages alternate; with lyrics the screen stays put."""
    if has_lyrics:
        return 0
    return 0 if frame % sum(MUSIC_PAGE_TICKS) < MUSIC_PAGE_TICKS[0] else 1


def _lyric_line(text: str, color: str) -> types.TextElement:
    font = "global" if needs_global_font(text) else "small"
    limit = SCROLL_AFTER_GLOBAL if font == "global" else SCROLL_AFTER
    extra = {"width": TEXT_W, "scroll_rate": SCROLL_RATE} if len(text) > limit else {}
    return _text("3", TEXT_X, GLOBAL_Y if font == "global" else 6, text, font, color, **extra)


def render_music(np: NowPlaying, thumb_name: str | None, pos: float, preview: str | None, frame: int,
                 lyric: str | None = None, has_lyrics: bool = False) -> types.DisplayElements:
    color = KIND_COLORS["music"]
    elements: list = [
        types.ImageElement(id="1", x=0, y=4, path=icon_filename("music")),
        types.ImageElement(id="2", x=9, y=0, path=thumb_name) if thumb_name else types.ImageElement(id="2", x=13, y=2, path=PLACEHOLDER),
    ]
    lyrics_mode = has_lyrics or lyric is not None
    page = 1 if preview else music_page(frame, lyrics_mode)
    if page == 0 and lyrics_mode:
        # Static layout: the current lyric line (or the title before it starts) over a thin bar.
        color_txt = rgba(WHITE if np.playing else TEXT_GREY)
        elements.append(_lyric_line(lyric, color_txt) if lyric else _title(np.title, color_txt))
        elements.append(_rect("5", TEXT_X, 14, TEXT_W, 2, rgba(TRACK)))
        if np.duration > 0:
            w = round(TEXT_W * max(0.0, min(1.0, pos / np.duration)))
            if w > 0:
                elements.append(_rect("6", TEXT_X, 14, w, 2, rgba(color, 0xFF if np.playing else 0x60)))
    elif page == 0:
        elements.append(_title(np.title, rgba(WHITE if np.playing else TEXT_GREY)))
        if np.artist and not needs_global_font(np.artist) and not needs_global_font(np.title):
            elements.append(_text("4", TEXT_X, 10, np.artist, "tiny", rgba(TEXT_GREY)))
    else:
        if preview:
            elements.append(_text("7", TEXT_X, 4, preview, "small", rgba(color)))
        else:
            elements.append(_text("7", TEXT_X, 4, format_time(pos), "small", rgba(WHITE if np.playing else TEXT_GREY)))
            elements.append(types.TextElement(id="8", x=71, y=4, text=f"/ {format_time(np.duration)}", font="tiny", color=rgba(TEXT_GREY), align="mid_right"))
        elements.append(_rect("5", TEXT_X, 10, TEXT_W, 5, rgba(TRACK)))
        if np.duration > 0:
            w = round(TEXT_W * max(0.0, min(1.0, pos / np.duration)))
            if w > 0:
                elements.append(_rect("6", TEXT_X, 10, w, 5, rgba(color, 0xFF if np.playing else 0x60)))
    return types.DisplayElements(application_name=APP, priority=PRIORITY, elements=elements)
