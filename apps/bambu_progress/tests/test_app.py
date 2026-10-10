import asyncio
from dataclasses import replace
from pathlib import Path

from busylib import exceptions, types

from apps.bambu_progress.app import DEMO_HOST, input_loop, parse_args, render_loop
from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState
from apps.bambu_progress.demo import DEMO_CONFIGS
from apps.bambu_progress.icons import APP
from apps.bambu_progress.ui import Ui


def test_parse_args_defaults():
    a = parse_args([])
    assert a.host is None and a.demo is False and a.once is False
    assert a.config == Path(__file__).resolve().parents[1] / "printers.toml"
    b = parse_args(["--demo", "--host", "1.2.3.4", "--once"])
    assert (b.demo, b.host, b.once) == (True, "1.2.3.4", True)
    assert DEMO_HOST == "127.0.0.1:8080"


class FakeBar:
    def __init__(self, draw_error=None):
        self.draws = []
        self.clears = 0
        self.sounds = []
        self.draw_error = draw_error
        self.ws_messages = []
        self.ws_rounds = 0
        self.clear_calls = []

    async def display_draw(self, elements):
        if self.draw_error:
            raise self.draw_error
        self.draws.append(elements)

    async def display_clear(self, **kw):
        assert kw["application_name"] == APP
        self.clears += 1
        self.clear_calls.append(kw)

    async def audio_play(self, *, stock_path, application_name):
        self.sounds.append(stock_path)

    async def stream_status_ws(self):
        self.ws_rounds += 1
        for m in self.ws_messages:
            yield m
        raise exceptions.BusyBarWebSocketError("closed", path="/api/status/ws")


async def test_render_loop_once_draws_current_ui():
    bar = FakeBar()
    ui = Ui(DEMO_CONFIGS)
    queue: asyncio.Queue = asyncio.Queue()
    st = PrinterState(name="P1S-A", connection=Connection.ONLINE, gcode_state=GcodeState.RUNNING, percent=10, last_report_at=1.0)
    queue.put_nowait((0, st))
    await render_loop(bar, ui, queue, once=True)
    assert len(bar.draws) == 1 and ui.states[0].percent == 10
    assert bar.draws[0].application_name == APP


async def test_render_loop_plays_sound_and_ignores_409():
    bar = FakeBar()
    ui = Ui(DEMO_CONFIGS)
    queue: asyncio.Queue = asyncio.Queue()
    on = PrinterState(name="P1S-A", connection=Connection.ONLINE, gcode_state=GcodeState.RUNNING, last_report_at=1.0)
    ui.apply_update(0, on)
    queue.put_nowait((0, replace(on, gcode_state=GcodeState.FINISH, percent=100)))
    await render_loop(bar, ui, queue, once=True)
    assert bar.sounds == ["busy/sounds/session_completed.snd"]

    busy = FakeBar(draw_error=exceptions.BusyBarAPIError("busy", status_code=409))
    await render_loop(busy, Ui(DEMO_CONFIGS), asyncio.Queue(), once=True)  # must not raise


async def test_render_loop_clears_once_when_hidden():
    bar = FakeBar()
    ui = Ui(DEMO_CONFIGS)
    ui.handle_input("button", "back")
    await render_loop(bar, ui, asyncio.Queue(), once=True)
    assert bar.draws == [] and bar.clears == 1


async def test_input_loop_feeds_ui_and_reconnects(monkeypatch):
    bar = FakeBar()
    bar.ws_messages = [{"updates": [{"input": {"encoder_event": {"delta": 1}}}]}]
    ui = Ui(DEMO_CONFIGS)
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("apps.bambu_progress.app.asyncio.sleep", fake_sleep)
    try:
        await input_loop(bar, ui)
    except asyncio.CancelledError:
        pass
    assert ui.selected == 1  # two rounds of the same message: reveal on 0, then 0 -> 1
    assert bar.ws_rounds == 2 and sleeps == [5.0, 5.0]


def test_configure_logging_quiets_busylib_unless_verbose():
    import logging

    from apps.bambu_progress.app import configure_logging

    configure_logging(verbose=False)
    assert logging.getLogger("busylib").level == logging.WARNING
    assert logging.getLogger("httpx2").level == logging.WARNING
    assert logging.getLogger("bambu-progress").getEffectiveLevel() == logging.INFO
    configure_logging(verbose=True)
    assert logging.getLogger("busylib").level == logging.DEBUG


async def test_painter_clears_stale_element_ids_on_screen_change():
    from apps.bambu_progress.app import Painter

    bar = FakeBar()
    painter = Painter(bar)
    ui = Ui(DEMO_CONFIGS)
    list_ids = {e.id for e in ui.render(0.0).elements}
    await painter.paint(ui.render(0.0))
    assert bar.clear_calls == [{"application_name": APP}]  # unknown leftovers: clear all once
    ui.handle_input("button", "ok")
    detail = ui.render(0.0)
    await painter.paint(detail)
    assert len(bar.draws) == 2
    stale = list_ids - {e.id for e in detail.elements}
    assert stale  # the screens differ, so...
    assert set(stale) <= set(bar.clear_calls[-1]["element_ids"]) and "element_ids" in bar.clear_calls[-1]   # ...drop the stale ids (and retyped ones), not the frame
    await painter.paint(detail)
    assert len(bar.clear_calls) == 2  # same ids again: no clear
    await painter.paint(None)
    assert bar.clear_calls[-1].get("element_ids") is None  # hidden: clear everything
    await painter.paint(None)
    assert bar.clears == 3  # already blank: no second clear


async def test_painter_moving_highlight_never_blanks_the_frame():
    from apps.bambu_progress.app import Painter

    bar = FakeBar()
    painter = Painter(bar)
    clock = {"t": 100.0}
    ui = Ui(DEMO_CONFIGS, now=lambda: clock["t"], layout="grid")
    await painter.paint(ui.render(clock["t"]))
    ui.handle_input("encoder", 1)
    await painter.paint(ui.render(clock["t"]))          # border appears: pure upsert
    ui.handle_input("encoder", 1)
    await painter.paint(ui.render(clock["t"]))          # border moves: same id, pure upsert
    assert len(bar.draws) == 3
    assert bar.clear_calls == [{"application_name": APP}]                                          # one full clear at start, never again
    assert [e.id for e in bar.draws[-1].elements] == ["?"]                                         # moving the border is an in-place update
    clock["t"] += 11
    ui.tick(clock["t"])
    await painter.paint(ui.render(clock["t"]))          # border expires: delete that one element only
    assert bar.clear_calls[-1] == {"application_name": APP, "element_ids": ["?"]}


async def test_painter_swaps_logo_image_for_animation_by_deleting_the_old_id():
    from apps.bambu_progress.app import Painter
    from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState

    bar = FakeBar()
    painter = Painter(bar)
    ui = Ui(DEMO_CONFIGS, now=lambda: 1.0, layout="grid")
    idle = PrinterState(name="A", connection=Connection.ONLINE, gcode_state=GcodeState.IDLE, last_report_at=1.0)
    ui.apply_update(0, idle)
    await painter.paint(ui.render(1.0))
    assert "0" in painter.shown and "1" not in painter.shown                   # cell 0: image id '0', animation id '1'
    ui.apply_update(0, replace(idle, gcode_state=GcodeState.RUNNING, percent=5))
    await painter.paint(ui.render(1.0))
    assert bar.clear_calls[-1] == {"application_name": APP, "element_ids": ["0"]}   # old image gone, animation drawn under its own id
    assert "1" in painter.shown and "0" not in painter.shown


async def test_painter_sends_only_changed_elements_so_animations_keep_running():
    from apps.bambu_progress.app import Painter
    from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState

    bar = FakeBar()
    painter = Painter(bar)
    ui = Ui(DEMO_CONFIGS, now=lambda: 1.0, layout="grid")
    run = PrinterState(name="A", connection=Connection.ONLINE, gcode_state=GcodeState.RUNNING, percent=5, last_report_at=1.0)
    ui.apply_update(0, run)
    await painter.paint(ui.render(1.0))
    first = bar.draws[-1]
    assert any(e.type == "animation" for e in first.elements)                 # first frame: everything, animation included
    await painter.paint(ui.render(1.0))                                        # nothing changed: a harmless probe only
    probe = bar.draws[-1].elements
    assert len(probe) == 1 and probe[0].type in ("rectangle", "text")
    ui.apply_update(0, replace(run, percent=6))
    await painter.paint(ui.render(1.0))                                        # percent changed: label + bar, not the animation
    sent = bar.draws[-1].elements
    assert sent and all(e.type != "animation" for e in sent) and any(e.type == "text" and e.text == "6" for e in sent)
    assert len(bar.clear_calls) == 1                                           # updated in place: nothing deleted
    assert bar.draws[-1].application_name == APP and bar.draws[-1].priority == first.priority
    bar.draw_error = exceptions.BusyBarAPIError("busy", status_code=409)
    await painter.paint(ui.render(1.0))                                        # rejected: forget everything
    bar.draw_error = None
    await painter.paint(ui.render(1.0))
    assert any(e.type == "animation" for e in bar.draws[-1].elements)         # ...and resend the whole frame


async def test_painter_sends_z_index_with_every_element():
    from apps.bambu_progress.app import Painter
    from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState

    bar = FakeBar()
    painter = Painter(bar)
    ui = Ui(DEMO_CONFIGS, now=lambda: 1.0, layout="grid")
    ui.apply_update(0, PrinterState(name="A", connection=Connection.ONLINE, gcode_state=GcodeState.RUNNING, percent=5, last_report_at=1.0))
    ui.handle_input("encoder", 1)
    await painter.paint(ui.render(1.0))
    assert all("z_index" in e.model_dump() for e in bar.draws[-1].elements)
    assert max(bar.draws[-1].elements, key=lambda e: e.z_index).id == "?"      # the border is the top-most element


async def test_painter_deletes_an_id_whose_element_type_changes_between_screens():
    from apps.bambu_progress.app import Painter
    from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState

    bar = FakeBar()
    painter = Painter(bar)
    ui = Ui(DEMO_CONFIGS, now=lambda: 1.0, layout="grid")
    for i in range(3):
        ui.apply_update(i, PrinterState(name="P", connection=Connection.ONLINE, gcode_state=GcodeState.RUNNING, percent=10 + i, last_report_at=1.0))
    await painter.paint(ui.render(1.0))
    grid_types = {e.id: e.type for e in bar.draws[-1].elements}
    ui.handle_input("button", "ok")                                            # grid -> detail at the same priority
    detail = ui.render(1.0)
    await painter.paint(detail)
    retyped = sorted(e.id for e in detail.elements if e.id in grid_types and grid_types[e.id] != e.type)
    assert retyped                                                             # the screens do share ids across kinds
    deleted = set(bar.clear_calls[-1]["element_ids"])
    assert set(retyped) <= deleted                                             # ...and every such id was deleted first
    assert all(e.id in {d.id for d in bar.draws[-1].elements} for e in detail.elements if e.id in retyped)   # then drawn fresh


async def test_painter_clears_everything_when_priority_drops():
    from apps.bambu_progress.app import Painter
    from apps.bambu_progress.render import PRIORITY_MAIN, PRIORITY_NOTICE

    bar = FakeBar()
    painter = Painter(bar)
    main = types.DisplayElements(application_name=APP, priority=PRIORITY_MAIN, elements=[
        types.TextElement(id="a", x=0, y=0, text="x", font="small")])
    notice = types.DisplayElements(application_name=APP, priority=PRIORITY_NOTICE, elements=[
        types.TextElement(id="n", x=0, y=0, text="!", font="small")])
    await painter.paint(main)
    await painter.paint(notice)
    assert bar.clear_calls[-1] == {"application_name": APP}      # priority changed: release the whole frame
    await painter.paint(main)
    assert bar.clear_calls[-1] == {"application_name": APP} and bar.clears == 3


async def test_painter_recovers_from_409_by_clearing_all(caplog):
    import logging

    from apps.bambu_progress.app import Painter

    bar = FakeBar()
    painter = Painter(bar)
    ui = Ui(DEMO_CONFIGS)
    frame = ui.render(0.0)
    await painter.paint(frame)
    bar.draw_error = exceptions.BusyBarAPIError("busy", status_code=409)
    with caplog.at_level(logging.WARNING, logger="bambu-progress"):
        await painter.paint(frame)  # rejected: must not raise
        await painter.paint(frame)  # still rejected: no second warning
    assert sum("409" in r.message or "rejected" in r.message for r in caplog.records) == 1
    bar.draw_error = None
    await painter.paint(frame)
    assert bar.clear_calls[-1] == {"application_name": APP}  # released the frame before redrawing
    assert len(bar.draws) == 2


async def test_wait_for_bar_retries_until_reachable():
    from apps.bambu_progress.app import wait_for_bar

    class FlakyBar:
        def __init__(self): self.calls = 0
        async def version(self):
            self.calls += 1
            if self.calls < 3:
                raise exceptions.BusyBarRequestError("All connection attempts failed", path="/api/version")
            from busylib import types
            return types.VersionInfo(api_semver="27.5.0")

    bar = FlakyBar(); sleeps = []
    async def fake_sleep(s): sleeps.append(s)
    v = await wait_for_bar(bar, sleep=fake_sleep, interval=5.0)
    assert v.api_semver == "27.5.0"
    assert bar.calls == 3 and sleeps == [5.0, 5.0]


async def test_painter_ignores_400_on_clear_and_still_draws():
    from apps.bambu_progress.app import Painter

    bar = FakeBar()
    calls = []

    async def clear_400(**kw):
        calls.append(kw)
        raise exceptions.BusyBarAPIError("Bad Request", status_code=400)
    bar.display_clear = clear_400
    painter = Painter(bar)
    ui = Ui(DEMO_CONFIGS)
    await painter.paint(ui.render(0.0))
    assert len(calls) == 1 and len(bar.draws) == 1        # a fresh app has nothing to clear: draw anyway
    await painter.paint(ui.render(0.0))
    assert len(calls) == 1 and len(bar.draws) == 2
