"""Pure rendering: (state, ui) -> busylib DisplayElements. No I/O here."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from busylib import types

from .bambu import Connection, GcodeState, PrinterState, effective_connection
from .config import PrinterConfig
from .events import Event, EventKind
from .icons import APP, DIM, GREEN, INK, RED, TEXT_GREY, TRACK, WHITE, YELLOW, anim_filename, icon_filename

PRIORITY_MAIN = 50
PRIORITY_NOTICE = 80
WIDTH = 72
HEIGHT = 16
ROW_H = 8
ROWS = 2
NAME_X = 10
LINE2_WIDTH = WIDTH - NAME_X
ROW_BAR_WIDTH = WIDTH - NAME_X   # 1px progress bar under each list row
SCROLL_AFTER = 15  # characters; longer line2 texts scroll
SCROLL_RATE = 20
OPACITY_SELECTED = 100
HIGHLIGHT_COLOR = WHITE  # same colour on every entry

# --- Element ids and stacking --------------------------------------------------------------------
# The firmware sorts an app's elements by `z_index` with an unstable qsort (canvas.c); an element
# sent without one gets 0, 10, 20, ... by its position in that request, so elements from different
# requests tie and the stacking flips whenever something is updated. Every element here therefore
# carries an explicit z_index, unique among the elements it can overlap.
Z_BACKDROP, Z_MARK, Z_BAR, Z_TEXT, Z_OUTLINE, Z_WORD, Z_BORDER, Z_RIPPLE = 0, 10, 20, 30, 40, 50, 90, 100
HIGHLIGHT_ID = "?"
_ID_CHARS = [chr(c) for c in range(48, 127) if chr(c) != HIGHLIGHT_ID]   # short ids: one character each
P_IMAGE, P_ANIM, P_NAME, P_LABEL, P_FILL, P_TRACK = range(6)   # the parts of one list row / grid cell


def eid(slot: int) -> str:
    return _ID_CHARS[slot]


def cell_id(cell: int, part: int) -> str:
    return eid(cell * 6 + part)


def rgba(hex6: str, alpha: int = 0xFF) -> str:
    return f"#{hex6.lstrip('#').upper()}{alpha:02X}"


def format_remaining(minutes: int) -> str:
    if minutes <= 0:
        return "<1m left"
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m left" if h else f"{m}m left"


def format_remaining_short(minutes: int) -> str:
    """The detail screen's right column is 27px wide: '2h25m', '45m', '<1m'."""
    if minutes <= 0:
        return "<1m"
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def display_rank(state: PrinterState, now: float) -> int:
    """List ordering: needs attention, printing, finished, idle, then not reachable."""
    conn = effective_connection(state, now)
    if conn is not Connection.ONLINE:
        return 4
    if state.has_error() or state.gcode_state is GcodeState.PAUSE:
        return 0
    if state.is_printing():
        return 1
    if state.gcode_state is GcodeState.FINISH:
        return 2
    return 3


def display_order(states: Sequence[PrinterState], now: float) -> list[int]:
    return sorted(range(len(states)), key=lambda i: (display_rank(states[i], now), i))


def list_window(selected: int, n: int, rows: int = ROWS) -> int:
    if n <= rows:
        return 0
    return (selected // rows) * rows


def progress_width(percent: int) -> int:
    return round(WIDTH * max(0, min(100, percent)) / 100)


@dataclass(frozen=True)
class Visual:
    icon: str
    icon_color: str
    label: str
    label_color: str
    bar_color: str | None
    show_track: bool
    line2: str
    anim: str | None = None   # a logo animation the bar plays itself (icons.ANIMATIONS); None: static icon


def visual(state: PrinterState, cfg: PrinterConfig, now: float, frame: int) -> Visual:
    conn = effective_connection(state, now)
    accent = cfg.color
    if conn is Connection.AUTH_ERROR:
        return Visual("logo", DIM, "AUTH", DIM, None, False, "bad access code")
    if conn is Connection.OFFLINE:
        return Visual("logo", DIM, "OFF", DIM, None, False, "offline")
    if conn is Connection.STALE:
        return Visual("logo", DIM, "STALE", DIM, None, False, "no data")
    if conn is Connection.CONNECTING:
        return Visual("hourglass", DIM, "...", DIM, None, False, "connecting")

    pct = f"{state.percent}%"
    if state.gcode_state is GcodeState.PAUSE and state.filament_out():
        return Visual("logo", YELLOW, pct, YELLOW, YELLOW, True, "FILAMENT")
    if state.has_error():
        return Visual("logo", RED, "ERR", RED, RED, True, state.hms_codes[0] if state.hms_codes else "error", anim="logo_error")
    gs = state.gcode_state
    if gs is GcodeState.FINISH:
        return Visual("logo", GREEN, "DONE", GREEN, GREEN, True, state.task_name or "done")   # finished: steady green, the full bar says it
    if gs is GcodeState.PAUSE:
        return Visual("logo", YELLOW, pct, YELLOW, YELLOW, True, "PAUSED")
    if gs is GcodeState.RUNNING:
        return Visual("logo", accent, pct, accent, accent, True, format_remaining(state.remaining_min), anim="logo_run")
    if gs is GcodeState.PREPARE:
        return Visual("logo", accent, "PREP", accent, None, True, "preparing")
    # idle: the printer's own colour, no label; grey is reserved for offline/stale/connecting so a
    # printer that is merely idle never looks disconnected
    return Visual("logo", accent, "", accent, None, False, "idle")


def _logo(cell: int, x: int, y: int, v: Visual, *, variant: str = "") -> types.AnimationElement | types.ImageElement:
    """The status mark: a looping on-device animation when the state has one, else a PNG.
    `variant`: "" (7x8 list mark), "grid_" (7x7) or "big_" (14x14, the detail screen).

    The firmware refuses to change an existing element's type under the same id (400), so the
    animation and the image have ids of their own; the Painter deletes whichever is no longer drawn."""
    if v.anim:
        return types.AnimationElement(id=cell_id(cell, P_ANIM), x=x, y=y, path=anim_filename(variant + v.anim, v.icon_color), loop=True, z_index=Z_MARK)
    icon = v.icon if variant == "" else "logo"   # only the list has room for hourglass etc.
    return types.ImageElement(id=cell_id(cell, P_IMAGE), x=x, y=y, path=icon_filename(variant + icon, v.icon_color), opacity=OPACITY_SELECTED, z_index=Z_MARK)


def _text(id: str, x: int, y: int, text: str, font: str, color: str, align: str = "mid_left", z: int = Z_TEXT, **extra) -> types.TextElement:
    return types.TextElement(id=id, x=x, y=y, text=text, font=font, color=color, align=align, z_index=z, **extra)


def _scroll(text: str, after: int, width: int) -> dict:
    """Extra TextElement kwargs that make a too-long line scroll inside `width`."""
    return {"width": width, "scroll_rate": SCROLL_RATE} if len(text) > after else {}


def _rect(id: str, x: int, y: int, w: int, h: int, color: str) -> types.RectangleElement:
    return types.RectangleElement(id=id, x=x, y=y, width=w, height=h, fill="solid", fill_colors=[color], border_width=0, z_index=Z_BAR)


def _bar(fill_id: str, track_id: str, x: int, y: int, width: int, height: int, percent: int,
         fill_color: str | None) -> list[types.RectangleElement]:
    """A progress bar as two rectangles that never overlap: the filled part and the rest of the track.
    The firmware's stacking order after partial redraws is not predictable (a fill re-sent alone can
    end up under its track), so nothing here relies on one rectangle covering another."""
    w = round(width * max(0, min(100, percent)) / 100) if fill_color else 0
    out: list[types.RectangleElement] = []
    if w > 0:
        out.append(_rect(fill_id, x, y, w, height, fill_color))
    if w < width:
        out.append(_rect(track_id, x + w, y, width - w, height, rgba(TRACK)))
    return out


def _border(id: str, x: int, y: int, w: int, h: int, color: str) -> types.RectangleElement:
    """1px outline used to show which entry the dial is on; above everything in its cell."""
    return types.RectangleElement(id=id, x=x, y=y, width=w, height=h, fill="none", border_width=1, border_color=color, z_index=Z_BORDER)


def render_list(
    states: Sequence[PrinterState], configs: Sequence[PrinterConfig], selected: int, now: float, frame: int,
    order: Sequence[int] | None = None, highlight: bool = True,
) -> types.DisplayElements:
    order = list(order) if order is not None else display_order(states, now)
    position = order.index(selected) if selected in order else 0
    start = list_window(position, len(order))
    elements: list = []
    for row, i in enumerate(order[start:start + ROWS]):
        state, cfg = states[i], configs[i]
        sel = highlight and i == selected
        y = row * ROW_H
        v = visual(state, cfg, now, frame)
        elements.append(_logo(row, 0, y, v))
        elements.append(_text(cell_id(row, P_NAME), NAME_X, y + 4, cfg.name[:8], "small", rgba(WHITE)))
        if sel:
            elements.append(_border(HIGHLIGHT_ID, 0, y, WIDTH, ROW_H, rgba(HIGHLIGHT_COLOR)))
        if v.label:
            elements.append(_text(cell_id(row, P_LABEL), WIDTH - 1, y + 4, v.label, "small", rgba(v.label_color), align="mid_right"))
        if v.show_track and v.bar_color:
            elements += _bar(cell_id(row, P_FILL), cell_id(row, P_TRACK), NAME_X, y + ROW_H - 1, ROW_BAR_WIDTH, 1, state.percent, rgba(v.bar_color))
    return types.DisplayElements(application_name=APP, priority=PRIORITY_MAIN, elements=elements)


# --- Detail screen -----------------------------------------------------------------------------------
# A dark flowing backdrop in the status colour (fx.detail_frames) with the rim the bar's own screens
# have; content keeps to columns 2-69 and rows 1-14 so the rim stays clear. Two blocks: on the left
# the 14x14 mark and the name in the biggest font; on the right the percentage (bold) over the
# remaining time (small, compact); a 2px bar under the text on rows 13-14.
# z_index: backdrop 0, mark 10, bar 20, texts 30, the enter ripple 100 over everything.
DETAIL_X = 2
DETAIL_MARK = 14
DETAIL_NAME_X = DETAIL_X + DETAIL_MARK + 2          # 18
DETAIL_RIGHT = WIDTH - DETAIL_X - 1                 # 69: right edge of the right block
DETAIL_RIGHT_W = 27                                 # the right block: enough for "100%" and "12h05m"
DETAIL_LINE2 = "#C8D0DC"
ENTER_ID = eid(13)
DETAIL_BACKDROP_ID = eid(14)   # not a cell slot: the mark image of cell 0 uses eid(0)
DETAIL_LINE2_MAX = 6           # small font, 27px: about six characters before it has to scroll


def detail_kind(state: PrinterState, now: float) -> str:
    if effective_connection(state, now) is not Connection.ONLINE:
        return "idle"
    if state.has_error():
        return "error"
    if state.gcode_state is GcodeState.PAUSE:
        return "pause"
    if state.is_printing():
        return "run"
    if state.gcode_state is GcodeState.FINISH:
        return "done"
    return "idle"


def render_detail(state: PrinterState, cfg: PrinterConfig, now: float, frame: int, entering: bool = False) -> types.DisplayElements:
    """`entering`: the first half second after OK, with the ripple overlay playing on top."""
    v = visual(state, cfg, now, frame)
    kind = detail_kind(state, now)
    backdrop_color = {"run": GREEN, "done": GREEN, "pause": YELLOW, "error": RED, "idle": DIM}[kind]
    elements: list = [
        types.AnimationElement(id=DETAIL_BACKDROP_ID, x=0, y=0, path=anim_filename(f"detail_{kind}", backdrop_color), loop=True, z_index=Z_BACKDROP),
        _logo(0, DETAIL_X, 1, v, variant="big_"),
        _text(cell_id(0, P_NAME), DETAIL_NAME_X, 7, cfg.name[:4], "extra_large", rgba(WHITE)),     # rows 2-11: a row of air above the bar
    ]
    if v.label:
        elements.append(_text(cell_id(0, P_LABEL), DETAIL_RIGHT, 4, v.label, "bold", rgba(v.label_color), align="mid_right"))   # rows 1-7
    line2 = format_remaining_short(state.remaining_min) if state.gcode_state is GcodeState.RUNNING and kind == "run" else v.line2
    if len(line2) > DETAIL_LINE2_MAX:
        elements.append(_text(cell_id(0, P_FILL + 1), DETAIL_RIGHT - DETAIL_RIGHT_W + 1, 10, line2, "small", rgba(DETAIL_LINE2),
                              width=DETAIL_RIGHT_W, scroll_rate=SCROLL_RATE))
    else:
        elements.append(_text(cell_id(0, P_FILL + 1), DETAIL_RIGHT, 10, line2, "small", rgba(DETAIL_LINE2), align="mid_right"))   # rows 8-12
    if v.show_track:
        alpha = 0x60 if state.gcode_state is GcodeState.PAUSE and frame % 2 else 0xFF
        elements += _bar(cell_id(1, P_IMAGE), cell_id(1, P_ANIM), DETAIL_NAME_X, 13, DETAIL_RIGHT - DETAIL_NAME_X + 1, 2, state.percent,
                         rgba(v.bar_color, alpha) if v.bar_color else None)
    if entering:
        elements.append(types.AnimationElement(id=ENTER_ID, x=0, y=0, path=anim_filename("enter", WHITE), loop=False, z_index=Z_RIPPLE))
    return types.DisplayElements(application_name=APP, priority=PRIORITY_MAIN, elements=elements)


# Notices look like the bar's own status screens: a full-screen animated backdrop in the status
# colour with the mark drawing itself in (fx.py), and one big outlined word drawn by the device.
_NOTICE_STYLE = {
    EventKind.FINISH: (GREEN, "notice_done", "DONE"),
    EventKind.PAUSE: (YELLOW, "notice_pause", "PAUSE"),
    EventKind.ERROR: (RED, "notice_error", "ERROR"),
}
NOTICE_WORD_X = 26
NOTICE_OUTLINE = "#000000"


def _outlined(x: int, y: int, text: str, font: str, color: str) -> list[types.TextElement]:
    """A text element with a 1px dark outline: four offset copies (z 40-43) under the word (z 50)."""
    shadows = [_text(eid(k), x + dx, y + dy, text, font, rgba(NOTICE_OUTLINE), z=Z_OUTLINE + k)
               for k, (dx, dy) in zip((1, 2, 3, 4), ((-1, 0), (1, 0), (0, -1), (0, 1)))]
    return [*shadows, _text(eid(5), x, y, text, font, rgba(color), z=Z_WORD)]


def render_notice(event: Event, cfg: PrinterConfig, show_name: bool = False) -> types.DisplayElements:
    """`show_name`: the printer's name instead of the status word (the two alternate while shown)."""
    color, backdrop, word = _NOTICE_STYLE[event.kind]
    elements = [
        types.AnimationElement(id=eid(0), x=0, y=0, path=anim_filename(backdrop, color), loop=True, z_index=Z_BACKDROP),
        *_outlined(NOTICE_WORD_X, 8, cfg.name[:5] if show_name else word, "extra_large", WHITE),
    ]
    return types.DisplayElements(
        application_name=APP, priority=PRIORITY_NOTICE, led_notification_color=rgba(color), elements=elements
    )


# --- 2x2 grid: four printers per screen, 36x8 cells ------------------------------------------------
# Rows: logo 7 tall on rows 0-6 / 8-14, name on rows 1-5 / 9-13, bar on row 6 / 14; rows 7 and 15 stay
# empty, so the two marks never touch and the highlight border's bottom line (row 7 / 15) covers nothing.
CELL_W = 36
CELL_H = 8
GRID_PER_PAGE = 4
CELL_TEXT_X = 8          # 7px logo plus 1px gap
CELL_X = (0, 37)         # second column one pixel further right so column 1's bar does not touch its logo
CELL_BAR_W = 27          # bar ends one pixel before the next column (col 1: x8-34, col 2: x45-71)
CELL_Y = (0, 8)


_GRID_LABELS = {"DONE": "", "STALE": "OLD", "AUTH": "AUT", "PREP": "PRE"}   # finished: the full bar says it


def grid_label(label: str) -> str:
    """The list labels shortened to three small-font glyphs so they fit beside a 3-char name."""
    if label.endswith("%"):
        return label[:-1]
    return _GRID_LABELS.get(label, label)[:3]


def grid_window(position: int, n: int) -> int:
    if n <= GRID_PER_PAGE:
        return 0
    return (position // GRID_PER_PAGE) * GRID_PER_PAGE


def render_grid(
    states: Sequence[PrinterState], configs: Sequence[PrinterConfig], selected: int, now: float, frame: int,
    order: Sequence[int] | None = None, highlight: bool = True,
) -> types.DisplayElements:
    order = list(order) if order is not None else display_order(states, now)
    position = order.index(selected) if selected in order else 0
    start = grid_window(position, len(order))
    elements: list = []
    for cell, i in enumerate(order[start:start + GRID_PER_PAGE]):
        state, cfg = states[i], configs[i]
        sel = highlight and i == selected
        x0 = CELL_X[cell % 2]
        y0 = CELL_Y[cell // 2]
        v = visual(state, cfg, now, frame)
        elements.append(_logo(cell, x0, y0, v, variant="grid_"))
        # small font (5px tall, ~4-5px/char) on rows 1-5 of the cell, centred on the 7-row mark and clear of
        # the dial border's line on row 0; the 1px bar sits on row 6
        elements.append(_text(cell_id(cell, P_NAME), x0 + CELL_TEXT_X, y0 + 3, cfg.name[:3], "small", rgba(WHITE)))
        if sel:
            # border occupies the gap column (x35 / x36) and the empty row (7 / 15): only the logo's top row is under it
            elements.append(_border(HIGHLIGHT_ID, (cell % 2) * CELL_W, y0, CELL_W, CELL_H, rgba(HIGHLIGHT_COLOR)))
        label = grid_label(v.label)
        if label:
            elements.append(_text(cell_id(cell, P_LABEL), x0 + CELL_TEXT_X + CELL_BAR_W - 1, y0 + 3, label, "small", rgba(v.label_color), align="mid_right"))
        if v.show_track and v.bar_color:
            elements += _bar(cell_id(cell, P_FILL), cell_id(cell, P_TRACK), x0 + CELL_TEXT_X, y0 + 6, CELL_BAR_W, 1, state.percent, rgba(v.bar_color))
    return types.DisplayElements(application_name=APP, priority=PRIORITY_MAIN, elements=elements)
