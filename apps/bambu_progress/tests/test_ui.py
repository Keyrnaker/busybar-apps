from dataclasses import replace

from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState
from apps.bambu_progress.config import PrinterConfig
from apps.bambu_progress.events import EventKind
from apps.bambu_progress.render import PRIORITY_MAIN, PRIORITY_NOTICE
from apps.bambu_progress.ui import NOTICE_ALTERNATE, NOTICE_SECONDS, SOUNDS, Screen, Ui, parse_input_events

CFG = [
    PrinterConfig("A", "1", "S1", "c", "#63E6BE"),
    PrinterConfig("B", "2", "S2", "c", "#FFBF47"),
    PrinterConfig("C", "3", "S3", "c", "#5096FF"),
]


def on(name, gs=GcodeState.RUNNING, **kw):
    return PrinterState(name=name, connection=Connection.ONLINE, gcode_state=gs, last_report_at=1.0, **kw)


def test_initial_state_and_navigation():
    ui = Ui(CFG)
    assert ui.screen is Screen.LIST and ui.selected == 0
    ui.handle_input("encoder", 1)    # first turn only shows the highlight on the top entry
    assert ui.selected == 0
    ui.handle_input("encoder", 1)
    ui.handle_input("encoder", 1)
    ui.handle_input("encoder", 1)
    assert ui.selected == 0  # wrapped
    ui.handle_input("encoder", -1)
    assert ui.selected == 2
    ui.handle_input("button", "ok")
    assert ui.screen is Screen.DETAIL
    ui.handle_input("encoder", 1)
    assert ui.screen is Screen.DETAIL and ui.selected == 0
    ui.handle_input("button", "back")
    assert ui.screen is Screen.LIST
    ui.handle_input("button", "back")
    assert ui.screen is Screen.HIDDEN
    assert ui.render(now=0.0) is None
    ui.handle_input("button", "start")
    assert ui.screen is Screen.LIST


def test_encoder_wraps_with_two_printers():
    ui = Ui(CFG[:2])
    ui.handle_input("encoder", 1)    # reveal
    ui.handle_input("encoder", -1)
    assert ui.selected == 1
    ui.handle_input("encoder", 3)
    assert ui.selected == 0


def test_render_priority_follows_screen():
    ui = Ui(CFG)
    assert ui.render(0.0).priority == PRIORITY_MAIN
    ui.handle_input("button", "ok")
    assert ui.render(0.0).priority == PRIORITY_MAIN


def test_update_detects_event_and_shows_notice_with_sound():
    ui = Ui(CFG)
    ui.apply_update(1, on("B"))
    events = ui.apply_update(1, on("B", GcodeState.FINISH, percent=100))
    assert [e.kind for e in events] == [EventKind.FINISH]
    assert ui.active is None and len(ui.queue) == 1
    ui.tick(now=10.0)
    assert ui.active is not None and ui.active.until == 10.0 + NOTICE_SECONDS
    assert ui.pop_sound() == SOUNDS[EventKind.FINISH]
    assert ui.pop_sound() is None
    assert ui.render(10.0).priority == PRIORITY_NOTICE
    ui.tick(now=10.0 + NOTICE_SECONDS + 0.1)
    assert ui.active is None
    assert ui.render(20.0).priority == PRIORITY_MAIN


def test_notice_is_a_big_mark_and_word_then_the_printer_name():
    ui = Ui(CFG)
    ui.apply_update(1, on("B", GcodeState.RUNNING, percent=99))
    ui.apply_update(1, on("B", GcodeState.FINISH, percent=100))
    ui.tick(10.0)
    out = ui.render(10.0)
    kinds = [e.type for e in out.elements]
    assert kinds == ["animation"] + ["text"] * 5                              # animated backdrop + outlined word
    backdrop, word = out.elements[0], out.elements[-1]
    assert backdrop.path.startswith("notice_done_") and backdrop.loop
    assert word.text == "DONE" and word.font == "extra_large" and word.color == "#FFFFFFFF"
    assert out.led_notification_color == "#3DDC84FF"
    named = ui.render(10.0 + NOTICE_ALTERNATE + 0.1).elements[-1]
    assert named.text == CFG[1].name[:5] and named.font == "extra_large"      # second half: who finished
    assert ui.render(10.0 + 2 * NOTICE_ALTERNATE - 0.1).elements[-1].text == CFG[1].name[:5]


def test_error_notice_stays_until_button():
    ui = Ui(CFG)
    ui.apply_update(0, on("A"))
    ui.apply_update(0, on("A", GcodeState.FAILED))
    ui.tick(1.0)
    assert ui.active.until is None
    ui.tick(10_000.0)
    assert ui.active is not None
    ui.handle_input("button", "ok")
    assert ui.active is None
    assert ui.screen is Screen.LIST  # the press only dismissed


def test_input_during_notice_dismisses_only():
    ui = Ui(CFG)
    ui.apply_update(2, on("C"))
    ui.apply_update(2, on("C", GcodeState.PAUSE))
    ui.tick(1.0)
    ui.handle_input("encoder", 1)
    assert ui.active is None and ui.selected == 0


def test_notice_queue_dedupes_and_orders():
    ui = Ui(CFG)
    ui.apply_update(0, on("A"))
    ui.apply_update(1, on("B"))
    ui.apply_update(0, on("A", GcodeState.PAUSE))
    ui.apply_update(0, on("A", GcodeState.RUNNING))
    ui.apply_update(0, on("A", GcodeState.PAUSE))  # duplicate while first still queued
    ui.apply_update(1, on("B", GcodeState.FINISH))
    assert [(e.printer_index, e.kind) for e in ui.queue] == [(0, EventKind.PAUSE), (1, EventKind.FINISH)]
    ui.tick(1.0)
    assert ui.active.event.printer_index == 0
    ui.tick(1.0 + NOTICE_SECONDS + 1)
    assert ui.active.event.printer_index == 1


def test_hidden_screen_restored_after_notice():
    ui = Ui(CFG)
    ui.handle_input("button", "back")
    assert ui.screen is Screen.HIDDEN
    ui.apply_update(0, on("A"))
    ui.apply_update(0, on("A", GcodeState.FINISH))
    ui.tick(1.0)
    assert ui.render(1.0) is not None
    ui.tick(1.0 + NOTICE_SECONDS + 1)
    assert ui.render(20.0) is None


def test_tick_advances_frame():
    ui = Ui(CFG)
    ui.tick(0.0)
    ui.tick(0.5)
    assert ui.frame == 2


def test_parse_input_events():
    msg = {
        "updates": [
            {"input": {"button_event": {"button": "ok", "action": "press"}}},
            {"input": {"button_event": {"button": "back", "action": "release"}}},
            {"input": {"encoder_event": {"delta": -2}}},
            {"input": {"encoder_event": {"delta": 0}}},
            {"display": {"brightness": 50}},
        ]
    }
    assert parse_input_events(msg) == [("button", "ok"), ("encoder", -2)]
    assert parse_input_events({"nope": 1}) == []


def test_start_button_acts_like_ok():
    ui = Ui(CFG)
    ui.handle_input("button", "start")
    assert ui.screen is Screen.DETAIL
    ui.handle_input("button", "back")
    ui.handle_input("button", "back")
    assert ui.screen is Screen.HIDDEN
    ui.handle_input("button", "start")
    assert ui.screen is Screen.LIST


def test_list_order_puts_attention_and_active_first_and_keeps_selection():
    ui = Ui(CFG, now=lambda: 1.0)   # states report at t=1.0; a real clock would make them all STALE
    ui.apply_update(0, on("A", GcodeState.FINISH, percent=100))
    ui.apply_update(1, on("B", GcodeState.FINISH, percent=100))
    ui.apply_update(2, on("C", GcodeState.RUNNING, percent=40))
    assert ui.order() == [2, 0, 1]          # running first, then the two finished in config order
    assert ui.selected == 0                 # selection is a printer index, unchanged by sorting
    ui.handle_input("encoder", 1)           # first turn only reveals the highlight on the top entry (C)
    assert ui.selected == 2
    ui.handle_input("encoder", 1)           # then it moves along the displayed order: C -> A
    assert ui.selected == 0
    ui.handle_input("encoder", 1)           # A -> B
    assert ui.selected == 1
    ui.handle_input("encoder", 1)           # B -> wraps to C (top)
    assert ui.selected == 2
    ui.apply_update(0, on("A", GcodeState.PAUSE, percent=50, hms_codes=("0700_2000_0002_0001",)))
    assert ui.order() == [0, 2, 1]          # paused (needs attention) jumps to the top
    assert ui.selected == 2                 # still C
    ui.apply_update(1, on("B", GcodeState.IDLE))
    ui.apply_update(2, PrinterState(name="C"))  # C lost connection -> connecting
    assert ui.order() == [0, 1, 2]          # paused, idle, connecting


def test_ui_grid_layout_renders_grid_and_dial_moves_through_all_cells():
    ui = Ui(CFG, now=lambda: 1.0, layout="grid")
    for i, n in enumerate("ABC"):
        ui.apply_update(i, on(n))
    out = ui.render(1.0)
    assert len([e for e in out.elements if e.type in ("image", "animation")]) == 3       # all three on one screen
    ui.handle_input("encoder", 1); ui.handle_input("encoder", 1); ui.handle_input("encoder", 1)
    assert ui.selected == 2
    assert Ui(CFG).layout == "list"


def test_dial_highlight_expires_after_ten_seconds_and_resets_selection():
    from apps.bambu_progress.ui import HIGHLIGHT_SECONDS
    clock = {"t": 100.0}
    ui = Ui(CFG, now=lambda: clock["t"], layout="grid")
    for i, n in enumerate("ABC"):
        ui.apply_update(i, on(n))
    assert ui.highlight_active() is False
    ui.handle_input("encoder", 1); ui.handle_input("encoder", 1); ui.handle_input("encoder", 1)
    assert ui.selected == 2 and ui.highlight_active() is True
    clock["t"] += HIGHLIGHT_SECONDS - 0.5
    ui.tick(clock["t"])
    assert ui.highlight_active() is True and ui.selected == 2
    clock["t"] += 1.0
    ui.tick(clock["t"])
    assert ui.highlight_active() is False and ui.selected == ui.order()[0] == 0   # back to the top entry
    ui.handle_input("button", "ok")                                                 # OK without highlight opens the top entry
    assert ui.screen is Screen.DETAIL and ui.selected == 0
    assert HIGHLIGHT_SECONDS == 10.0


def test_render_grid_border_only_while_highlighted():
    clock = {"t": 100.0}
    ui = Ui(CFG, now=lambda: clock["t"], layout="grid")
    for i, n in enumerate("ABC"):
        ui.apply_update(i, on(n))
    out = ui.render(clock["t"])
    assert [e for e in out.elements if e.type == "rectangle" and e.fill == "none"] == []        # no border
    assert all(e.opacity == 100 for e in out.elements if e.type == "image")                     # nobody dimmed
    def border():
        bs = [e for e in ui.render(clock["t"]).elements if e.type == "rectangle" and e.fill == "none"]
        assert len(bs) == 1
        return bs[0]
    ui.handle_input("encoder", 1)                                                                # first turn: row 1, column 1
    b = border()
    assert (b.x, b.y, b.width, b.height) == (0, 0, 36, 8)
    assert b.border_color == "#FFFFFFFF" and b.border_width == 1 and b.id == "?"
    assert all(e.opacity == 100 for e in ui.render(clock["t"]).elements if e.type == "image")   # still nobody dimmed
    ui.handle_input("encoder", 1)                                                                # row 1, column 2
    assert (border().x, border().y) == (36, 0)
    ui.handle_input("encoder", 1)                                                                # row 2, column 1
    b = border()
    assert (b.x, b.y, b.width, b.height) == (0, 8, 36, 8)                                        # fully on screen (rows 8-15)
    bars = [e for e in ui.render(clock["t"]).elements if e.type == "rectangle" and e.fill == "solid" and e.y >= 8]
    assert bars and all(e.y < b.y + b.height - 1 for e in bars)                                  # bar (row 14) is above the bottom line
