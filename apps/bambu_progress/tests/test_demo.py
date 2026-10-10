import asyncio

from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState
from apps.bambu_progress.demo import DEMO_CONFIGS, SCENARIOS, DemoMonitor
from apps.bambu_progress.events import EventKind, detect


async def _collect(index):
    queue: asyncio.Queue = asyncio.Queue()
    holds: list[float] = []

    async def sleep(s):
        holds.append(s)

    await DemoMonitor(index, DEMO_CONFIGS[index], queue, sleep=sleep, clock=lambda: 7.0, loop=False).run()
    states = []
    while not queue.empty():
        states.append(queue.get_nowait()[1])
    return states, holds


def test_three_demo_printers_with_distinct_colors():
    assert len(DEMO_CONFIGS) == 3 == len(SCENARIOS)
    assert len({c.color for c in DEMO_CONFIGS}) == 3


async def test_scenario_0_runs_to_finish_then_idle():
    states, holds = await _collect(0)
    assert states[0].connection is Connection.ONLINE and states[0].gcode_state is GcodeState.RUNNING
    assert states[0].last_report_at == 7.0
    assert any(s.gcode_state is GcodeState.FINISH and s.percent == 100 for s in states)
    assert states[-1].gcode_state is GcodeState.IDLE
    assert len(holds) == len(states) and sum(holds) < 60


async def test_scenario_1_pauses_for_filament_then_finishes():
    states, _ = await _collect(1)
    kinds = []
    prev = PrinterState(name="x")
    for s in states:
        kinds += [(e.kind, e.message) for e in detect(1, prev, s)]
        prev = s
    assert kinds == [(EventKind.PAUSE, "FILAMENT"), (EventKind.FINISH, "DONE")]


async def test_scenario_2_fails_with_error_code():
    states, _ = await _collect(2)
    failed = [s for s in states if s.gcode_state is GcodeState.FAILED]
    assert failed and failed[0].print_error != 0 and failed[0].hms_codes
    assert states[-1].print_error == 0 and states[-1].gcode_state is GcodeState.IDLE
