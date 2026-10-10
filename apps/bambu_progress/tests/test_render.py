from dataclasses import replace

from busylib import types

from apps.bambu_progress.bambu import STALE_AFTER, Connection, GcodeState, PrinterState
from apps.bambu_progress.config import PrinterConfig
from apps.bambu_progress.events import Event, EventKind
from apps.bambu_progress.icons import DARK_RED, DIM, GREEN, LIME, RED, TRACK, WHITE, YELLOW, anim_filename, icon_filename
from apps.bambu_progress.render import (
    HIGHLIGHT_ID, P_ANIM, P_FILL, P_IMAGE, P_LABEL, P_NAME, P_TRACK, Z_BACKDROP, Z_BAR, Z_BORDER, Z_MARK, Z_OUTLINE, Z_RIPPLE, Z_TEXT, Z_WORD, cell_id,
    PRIORITY_MAIN,
    PRIORITY_NOTICE,
    format_remaining,
    list_window,
    progress_width,
    render_detail,
    render_list,
    render_notice,
    rgba,
    visual,
)

CFG = [
    PrinterConfig("P1S-A", "1", "S1", "c", "#63E6BE"),
    PrinterConfig("P1S-B", "2", "S2", "c", "#FFBF47"),
    PrinterConfig("X1C", "3", "S3", "c", "#5096FF"),
]
NOW = 1000.0
ON = PrinterState(name="P1S-A", connection=Connection.ONLINE, last_report_at=NOW)


def running(pct=67, mins=72):
    return replace(ON, gcode_state=GcodeState.RUNNING, percent=pct, remaining_min=mins)


def by_type(elements, kind):
    return [e for e in elements.elements if e.type == kind]


def logos(elements):
    """The status marks: on-device animations while printing/done/error, PNG images otherwise."""
    return [e for e in elements.elements if e.type in ("image", "animation")]


def test_format_remaining_short_fits_the_detail_column():
    from apps.bambu_progress.render import format_remaining_short
    assert format_remaining_short(0) == "<1m" and format_remaining_short(45) == "45m"
    assert format_remaining_short(72) == "1h12m" and format_remaining_short(125) == "2h05m" and format_remaining_short(725) == "12h05m"


def test_rgba_and_format_remaining():
    assert rgba("#3DDC84") == "#3DDC84FF"
    assert rgba("#3ddc84", 0x60) == "#3DDC8460"
    assert format_remaining(72) == "1h 12m left"
    assert format_remaining(12) == "12m left"
    assert format_remaining(0) == "<1m left"
    assert format_remaining(125) == "2h 5m left"


def test_list_window_small_counts():
    assert [list_window(i, 3) for i in range(3)] == [0, 0, 2]
    assert [list_window(i, 2) for i in range(2)] == [0, 0]
    assert list_window(0, 1) == 0


def test_progress_width():
    assert progress_width(0) == 0
    assert progress_width(50) == 36
    assert progress_width(100) == 72


def test_visual_states():
    v = visual(running(), CFG[0], NOW, frame=0)
    assert (v.icon, v.icon_color, v.label, v.bar_color, v.anim) == ("logo", "#63E6BE", "67%", "#63E6BE", "logo_run")
    assert all(visual(running(), CFG[0], NOW, frame=f).anim == "logo_run" for f in range(1, 5))   # the bar animates; frames are irrelevant
    assert v.line2 == "1h 12m left"

    done = replace(ON, gcode_state=GcodeState.FINISH, percent=100, task_name="benchy.3mf")
    v = visual(done, CFG[0], NOW, 0)
    assert (v.icon, v.icon_color, v.label, v.bar_color, v.line2) == ("logo", GREEN, "DONE", GREEN, "benchy.3mf")
    assert visual(done, CFG[0], NOW, 1).anim is None and visual(done, CFG[0], NOW, 1).icon_color == GREEN   # finished: steady green

    paused = replace(running(), gcode_state=GcodeState.PAUSE)
    v = visual(paused, CFG[0], NOW, 0)
    assert (v.icon, v.icon_color, v.label_color, v.bar_color, v.line2) == ("logo", YELLOW, YELLOW, YELLOW, "PAUSED")
    assert visual(paused, CFG[0], NOW, 1).icon_color == YELLOW  # steady; the bar blinks instead

    err = replace(running(), print_error=1, hms_codes=("0300_0100_0002_0001",))
    v = visual(err, CFG[0], NOW, 0)
    assert (v.icon, v.icon_color, v.label, v.line2) == ("logo", RED, "ERR", "0300_0100_0002_0001")
    assert visual(err, CFG[0], NOW, 1).icon_color == RED and v.anim == "logo_error"   # red/dark-red pulse on the device

    idle = replace(ON, gcode_state=GcodeState.IDLE)
    v = visual(idle, CFG[0], NOW, 0)
    assert (v.icon, v.icon_color, v.label, v.bar_color, v.line2) == ("logo", CFG[0].color, "", None, "idle")
    offline = visual(replace(ON, connection=Connection.OFFLINE), CFG[0], NOW, 0)
    assert offline.icon_color == DIM and v.icon_color != offline.icon_color   # idle must not look like offline

    prep = replace(ON, gcode_state=GcodeState.PREPARE)
    v = visual(prep, CFG[0], NOW, 0)
    assert (v.icon, v.icon_color, v.label, v.bar_color, v.show_track) == ("logo", "#63E6BE", "PREP", None, True)


def test_visual_connection_states():
    assert visual(PrinterState(name="A"), CFG[0], NOW, 0).line2 == "connecting"
    assert visual(PrinterState(name="A"), CFG[0], NOW, 0).icon == "hourglass"
    off = replace(ON, connection=Connection.OFFLINE)
    assert (visual(off, CFG[0], NOW, 0).label, visual(off, CFG[0], NOW, 0).icon) == ("OFF", "logo")
    stale = replace(running(), last_report_at=NOW - STALE_AFTER - 1)
    assert visual(stale, CFG[0], NOW, 0).label == "STALE"
    auth = replace(ON, connection=Connection.AUTH_ERROR)
    assert visual(auth, CFG[0], NOW, 0).line2 == "bad access code"


def test_render_list_two_rows_selected_highlighted():
    states = [running(), replace(ON, gcode_state=GcodeState.IDLE, name="P1S-B"), replace(ON, name="X1C")]
    out = render_list(states, CFG, selected=1, now=NOW, frame=0)
    assert out.application_name == "bambu-progress" and out.priority == PRIORITY_MAIN
    images = logos(out)
    texts = by_type(out, "text")
    # rows 0 and 1 visible (window starts at 0): one status-carrying logo per row
    assert [(i.x, i.y) for i in images] == [(0, 0), (0, 8)]
    assert images[0].type == "animation" and images[0].path == anim_filename("logo_run", "#63E6BE") and images[0].loop   # running: the bar animates
    assert images[0].id == cell_id(0, P_ANIM) and images[1].id == cell_id(1, P_IMAGE)   # an animation never reuses an image's id (type change -> 400)
    assert images[1].type == "image" and images[1].path == icon_filename("logo", CFG[1].color) and images[1].opacity == 100  # idle: own colour; nobody is dimmed
    names = [t for t in texts if t.x == 10]
    assert [t.text for t in names] == ["P1S-A", "P1S-B"]
    assert names[0].color == rgba(WHITE) and names[1].color == rgba(WHITE)   # names are never greyed out
    labels = [t for t in texts if t.x == 71]
    assert [t.text for t in labels] == ["67%"]  # idle row has no label


def test_render_list_third_printer_alone_on_second_page():
    states = [running(), running(), replace(running(), name="X1C")]
    out = render_list(states, CFG, selected=2, now=NOW, frame=0)
    assert [i.y for i in logos(out)] == [0]
    assert by_type(out, "text")[0].text == "X1C"


def test_render_detail_running_bar():
    out = render_detail(running(50), CFG[0], NOW, frame=0)
    rects = by_type(out, "rectangle")
    # fill, then the rest of the track: two rectangles that never overlap; 2px tall on rows 13-14
    # under the text, from the name's left edge to the right block's edge
    assert [(r.x, r.y, r.width, r.height) for r in rects] == [(18, 13, 26, 2), (44, 13, 26, 2)]
    assert rects[0].fill_colors == [rgba("#63E6BE")] and rects[1].fill_colors == [rgba(TRACK)]
    texts = {t.text: t for t in by_type(out, "text")}
    assert set(texts) == {"P1S-", "50%", "1h12m"}                              # left: name (4 chars max); right: percent over compact time
    assert texts["P1S-"].font == "extra_large" and (texts["P1S-"].x, texts["P1S-"].y) == (18, 7)
    assert texts["50%"].font == "bold" and (texts["50%"].x, texts["50%"].y, texts["50%"].align) == (69, 4, "mid_right")
    assert texts["1h12m"].font == "small" and (texts["1h12m"].x, texts["1h12m"].y, texts["1h12m"].align) == (69, 10, "mid_right")
    backdrop = out.elements[0]
    assert backdrop.type == "animation" and backdrop.path.startswith("detail_run_") and backdrop.loop and backdrop.id == ">"
    from apps.bambu_progress.render import ENTER_ID
    assert not any(e.id == ENTER_ID for e in out.elements)
    entering = render_detail(running(50), CFG[0], NOW, frame=0, entering=True)
    ripple = entering.elements[-1]
    assert ripple.type == "animation" and ripple.id == ENTER_ID and ripple.path.startswith("enter_") and ripple.loop is False
    mark = [e for e in logos(out) if not e.path.startswith("detail_")][0]
    assert mark.path == anim_filename("big_logo_run", "#63E6BE") and mark.type == "animation" and (mark.x, mark.y) == (2, 1)   # 14x14 on rows 1-14


def test_render_detail_paused_blinks_and_idle_has_no_bar():
    paused = replace(running(50), gcode_state=GcodeState.PAUSE)
    fill0 = by_type(render_detail(paused, CFG[0], NOW, 0), "rectangle")[0].fill_colors[0]
    fill1 = by_type(render_detail(paused, CFG[0], NOW, 1), "rectangle")[0].fill_colors[0]
    assert {fill0, fill1} == {rgba(YELLOW), rgba(YELLOW, 0x60)}
    idle = replace(ON, gcode_state=GcodeState.IDLE)
    out = render_detail(idle, CFG[0], NOW, 0)
    assert by_type(out, "rectangle") == []
    assert by_type(out, "image")[0].path == icon_filename("big_logo", CFG[0].color)   # the 14x14 mark
    assert out.elements[0].path.startswith("detail_idle_")


def test_render_detail_zero_percent_has_track_only():
    out = render_detail(running(0), CFG[0], NOW, 0)
    assert len(by_type(out, "rectangle")) == 1


def test_render_detail_finish_scrolls_long_task_name():
    done = replace(ON, gcode_state=GcodeState.FINISH, percent=100, task_name="a_very_long_file_name_here.3mf")
    out = render_detail(done, CFG[0], NOW, 0)
    line2 = [t for t in by_type(out, "text") if t.text.startswith("a_very")][0]
    assert line2.font == "small" and line2.width == 27 and line2.x == 43 and line2.scroll_rate and line2.scroll_rate > 0   # too long for the right block: scrolls inside it
    assert out.elements[0].path.startswith("detail_done_")


def test_visual_filament_pause_with_print_error_is_yellow():
    paused = replace(running(), gcode_state=GcodeState.PAUSE, print_error=0x0700_2001,
                     hms_codes=("0700_2000_0002_0001",))
    v = visual(paused, CFG[0], NOW, 0)
    assert (v.icon, v.icon_color, v.bar_color, v.line2) == ("logo", YELLOW, YELLOW, "FILAMENT")


def test_render_list_rows_have_thin_progress_bars():   # no dial highlight: bars only
    states = [running(50), replace(ON, gcode_state=GcodeState.IDLE, name="P1S-B"), replace(ON, name="X1C")]
    out = render_list(states, CFG, selected=0, now=NOW, frame=0, highlight=False)
    rects = by_type(out, "rectangle")
    # row 0 (running 50%): 1px track under the name plus a fill, row 1 (idle): nothing
    assert [(r.x, r.y, r.width, r.height) for r in rects] == [(10, 7, 31, 1), (41, 7, 31, 1)]   # fill, then the rest of the track
    assert rects[0].fill_colors == [rgba("#63E6BE")] and rects[1].fill_colors == [rgba(TRACK)]
    # second page: X1C (row 0 there) is CONNECTING-> no bar; a paused printer on row 1 gets a yellow bar at y=15
    states2 = [running(50), replace(running(80), gcode_state=GcodeState.PAUSE, name="P1S-B"), replace(ON, name="X1C")]
    out2 = render_list(states2, CFG, selected=0, now=NOW, frame=0, order=[0, 1, 2], highlight=False)  # geometry test: fixed order
    rects2 = by_type(out2, "rectangle")
    assert [(r.x, r.y, r.width) for r in rects2] == [(10, 7, 31), (41, 7, 31), (10, 15, 50), (60, 15, 12)]
    assert rects2[2].fill_colors == [rgba(YELLOW)]
    # done: full green bar; zero percent: track only
    done = replace(ON, gcode_state=GcodeState.FINISH, percent=100)
    r3 = by_type(render_list([done], CFG[:1], 0, NOW, 0, highlight=False), "rectangle")
    assert [(r.width, r.fill_colors[0]) for r in r3] == [(62, rgba(GREEN))]                 # full: no track left
    r4 = by_type(render_list([running(0)], CFG[:1], 0, NOW, 0, highlight=False), "rectangle")
    assert [(r.width, r.fill_colors[0]) for r in r4] == [(62, rgba(TRACK))]                 # empty: track only


def test_render_list_honours_display_order_and_windows_on_selected_position():
    states = [replace(ON, gcode_state=GcodeState.FINISH, percent=100), replace(ON, gcode_state=GcodeState.FINISH, percent=100, name="P1S-B"), replace(running(40), name="X1C")]
    out = render_list(states, CFG, selected=2, now=NOW, frame=0, order=[2, 0, 1])
    names = [t.text for t in by_type(out, "text") if t.x == 10]
    assert names == ["X1C", "P1S-A"]        # first page in display order, X1C (selected) on top
    out2 = render_list(states, CFG, selected=1, now=NOW, frame=0, order=[2, 0, 1])
    names2 = [t.text for t in by_type(out2, "text") if t.x == 10]
    assert names2 == ["P1S-B"]              # selected sits at position 2 -> second page


def test_render_grid_four_cells_per_page():
    from apps.bambu_progress.render import CELL_W, CELL_H, grid_window, render_grid
    cfg4 = CFG + [PrinterConfig("P1S-B", "4", "S4", "c", "#FF5E93")]
    states = [running(67), replace(ON, gcode_state=GcodeState.IDLE, name="P1S-B"), replace(running(100), gcode_state=GcodeState.FINISH, name="X1C"), replace(ON, connection=Connection.OFFLINE, name="P1S-B")]
    assert (CELL_W, CELL_H) == (36, 8)
    out = render_grid(states, cfg4, selected=1, now=NOW, frame=0, order=[0, 1, 2, 3])
    L = {e.id: e for e in logos(out)}
    assert set(L) == {cell_id(0, P_ANIM), cell_id(1, P_IMAGE), cell_id(2, P_IMAGE), cell_id(3, P_IMAGE)}   # animation and image have ids of their own
    logo_of = [L[cell_id(0, P_ANIM)], L[cell_id(1, P_IMAGE)], L[cell_id(2, P_IMAGE)], L[cell_id(3, P_IMAGE)]]
    assert [(e.x, e.y) for e in logo_of] == [(0, 0), (37, 0), (0, 8), (37, 8)]   # column 2 one px further right
    assert logo_of[0].path == anim_filename("grid_logo_run", "#63E6BE") and logo_of[2].path == icon_filename("grid_logo", GREEN)   # printing animates; finished is a steady green mark
    assert logo_of[1].path == icon_filename("grid_logo", "#FFBF47") and logo_of[3].path == icon_filename("grid_logo", DIM)   # idle / offline: static PNG
    assert all(e.opacity == 100 for e in logo_of[1:])                       # no dimming: only the border marks the selection
    texts = {e.id: e for e in by_type(out, "text")}
    n0, l0 = texts[cell_id(0, P_NAME)], texts[cell_id(0, P_LABEL)]
    assert n0.text == "P1S" and n0.font == "small" and (n0.x, n0.y) == (8, 3)   # name cut to 3 chars, 5px font on rows 1-5 (row 0 is the border's)
    assert l0.font == "small"
    assert l0.text == "67" and l0.align == "mid_right" and (l0.x, l0.y) == (34, 3)   # grid labels: 3 chars max
    assert texts[cell_id(1, P_NAME)].color == rgba(WHITE) and n0.color == rgba(WHITE)   # names are never greyed out
    assert cell_id(1, P_LABEL) not in texts and cell_id(2, P_LABEL) not in texts   # idle and finished: no label (the full bar says it)
    assert texts[cell_id(3, P_LABEL)].text == "OFF"
    rects = {e.id: e for e in by_type(out, "rectangle")}
    w = round(27 * 0.67)
    f0, t0, f2 = rects[cell_id(0, P_FILL)], rects[cell_id(0, P_TRACK)], rects[cell_id(2, P_FILL)]
    assert (f0.x, f0.y, f0.width, f0.height) == (8, 6, w, 1)                # fill under the text
    assert (t0.x, t0.y, t0.width, t0.height) == (8 + w, 6, 27 - w, 1)       # the rest of the track, ends before the column gap
    assert f2.x == 8 and f2.y == 14 and f2.width == 27 and cell_id(2, P_TRACK) not in rects   # finished: full bar, no track
    assert cell_id(1, P_TRACK) not in rects and cell_id(3, P_TRACK) not in rects   # idle/offline: no bar
    assert grid_window(5, 6) == 4 and grid_window(3, 4) == 0 and grid_window(0, 3) == 0


def test_render_grid_partial_page_and_window():
    from apps.bambu_progress.render import render_grid
    states = [running(10), running(20), running(30)]
    out = render_grid(states, CFG, selected=2, now=NOW, frame=0)      # 3 printers: one page, 3 cells
    assert len(logos(out)) == 3
    five = [running(p) for p in (1, 2, 3, 4, 5)]
    cfg5 = CFG + [PrinterConfig("D", "4", "S4", "c", "#FF5E93"), PrinterConfig("E", "5", "S5", "c", "#63E6BE")]
    out5 = render_grid(five, cfg5, selected=4, now=NOW, frame=0, order=[0, 1, 2, 3, 4])
    imgs = logos(out5)
    assert len(imgs) == 1 and (imgs[0].x, imgs[0].y) == (0, 0)             # second page: the 5th alone, top-left


def test_grid_label_is_at_most_three_chars():
    from apps.bambu_progress.render import grid_label
    assert grid_label("100%") == "100" and grid_label("67%") == "67" and grid_label("DONE") == ""
    assert grid_label("STALE") == "OLD" and grid_label("AUTH") == "AUT" and grid_label("PREP") == "PRE"
    assert grid_label("ERR") == "ERR" and grid_label("OFF") == "OFF" and grid_label("...") == "..." and grid_label("") == ""
    for raw in ("100%", "DONE", "STALE", "AUTH", "PREP", "ERR", "OFF", "..."):
        assert len(grid_label(raw)) <= 3


def test_render_list_border_when_highlighted():
    states = [running(), replace(ON, gcode_state=GcodeState.IDLE, name="P1S-B"), replace(ON, name="X1C")]
    plain = render_list(states, CFG, selected=1, now=NOW, frame=0, order=[0, 1, 2], highlight=False)
    assert not [e for e in plain.elements if e.type == "rectangle" and e.fill == "none"]
    assert all(e.opacity == 100 for e in by_type(plain, "image"))
    hi = render_list(states, CFG, selected=1, now=NOW, frame=0, order=[0, 1, 2], highlight=True)
    borders = [e for e in hi.elements if e.type == "rectangle" and e.fill == "none"]
    assert len(borders) == 1 and (borders[0].x, borders[0].y, borders[0].width, borders[0].height) == (0, 8, 72, 8)
    assert borders[0].border_color == rgba(WHITE) and borders[0].id == HIGHLIGHT_ID   # same colour and id wherever it is
    assert all(e.opacity == 100 for e in by_type(hi, "image"))                   # highlighting dims nothing


def test_render_notice_is_an_animated_backdrop_with_an_outlined_word():
    from apps.bambu_progress.icons import YELLOW
    from apps.bambu_progress.render import NOTICE_OUTLINE, PRIORITY_NOTICE, render_notice
    out = render_notice(Event(0, EventKind.PAUSE, "FILAMENT"), CFG[0])
    assert out.priority == PRIORITY_NOTICE and out.led_notification_color == rgba(YELLOW)
    assert [e.type for e in out.elements] == ["animation"] + ["text"] * 5    # backdrop, 4 outline copies, the word
    fx = out.elements[0]
    assert fx.path == anim_filename("notice_pause", YELLOW) and fx.loop and (fx.x, fx.y) == (0, 0)
    texts = out.elements[1:]
    assert all(t.text == "PAUSE" and t.font == "extra_large" for t in texts)
    assert [t.color for t in texts] == [rgba(NOTICE_OUTLINE)] * 4 + [rgba(WHITE)]
    assert {(t.x - 26, t.y - 8) for t in texts} == {(-1, 0), (1, 0), (0, -1), (0, 1), (0, 0)}
    err = render_notice(Event(0, EventKind.ERROR, "0300_0100_0002_0001"), CFG[0], show_name=True)
    assert err.elements[0].path == anim_filename("notice_error", RED) and err.elements[-1].text == CFG[0].name[:5]
    assert render_notice(Event(0, EventKind.FINISH, "DONE"), CFG[0]).elements[-1].text == "DONE"


def test_every_element_carries_an_explicit_z_index_that_orders_overlaps():
    from apps.bambu_progress.render import render_grid, render_notice
    states = [running(67), replace(ON, gcode_state=GcodeState.IDLE, name="P1S-B"), replace(running(100), gcode_state=GcodeState.FINISH, name="X1C")]
    frames = [
        render_grid(states, CFG, selected=0, now=NOW, frame=0, order=[0, 1, 2], highlight=True),
        render_list(states, CFG, selected=0, now=NOW, frame=0, order=[0, 1, 2], highlight=True),
        render_detail(running(50), CFG[0], NOW, 0, entering=True),
        render_notice(Event(0, EventKind.FINISH, "DONE"), CFG[0]),
        render_detail(replace(ON, gcode_state=GcodeState.IDLE), CFG[0], NOW, 0, entering=True),   # static mark image + backdrop
        render_detail(replace(ON, connection=Connection.OFFLINE), CFG[0], NOW, 0),
    ]
    for out in frames:
        ids = [e.id for e in out.elements]
        assert len(ids) == len(set(ids)) and all(len(i) == 1 for i in ids), ids
        assert all(isinstance(getattr(e, "z_index", None), int) and e.z_index >= 0 for e in out.elements)
        assert all("z_index" in e.model_dump() for e in out.elements)                  # it is sent to the bar
    grid = {e.id: e for e in frames[0].elements}
    assert grid[HIGHLIGHT_ID].z_index == Z_BORDER > max(e.z_index for i, e in grid.items() if i != HIGHLIGHT_ID)
    assert all(e.z_index == Z_MARK for e in frames[0].elements if e.type in ("image", "animation"))
    detail = frames[2].elements
    assert detail[0].z_index == Z_BACKDROP and detail[-1].z_index == Z_RIPPLE
    assert all(Z_BACKDROP < e.z_index < Z_RIPPLE for e in detail[1:-1])
    notice = frames[3].elements
    assert notice[0].z_index == Z_BACKDROP and notice[-1].z_index == Z_WORD
    outline_z = [e.z_index for e in notice[1:-1]]
    assert len(set(outline_z)) == 4 and all(Z_OUTLINE <= z < Z_WORD for z in outline_z)   # the four copies never tie
def test_detail_kind_follows_the_status():
    from apps.bambu_progress.render import detail_kind
    assert detail_kind(running(50), NOW) == "run"
    assert detail_kind(replace(ON, gcode_state=GcodeState.FINISH, percent=100), NOW) == "done"
    assert detail_kind(replace(running(50), gcode_state=GcodeState.PAUSE), NOW) == "pause"
    assert detail_kind(replace(running(), print_error=1, hms_codes=("0300_0100_0002_0001",)), NOW) == "error"
    assert detail_kind(replace(ON, gcode_state=GcodeState.IDLE), NOW) == "idle"
    assert detail_kind(replace(ON, connection=Connection.OFFLINE), NOW) == "idle"
