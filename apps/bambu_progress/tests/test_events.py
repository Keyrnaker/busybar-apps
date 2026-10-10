from dataclasses import replace

from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState
from apps.bambu_progress.events import Event, EventKind, detect

ON = PrinterState(name="A", connection=Connection.ONLINE, last_report_at=1.0)


def running(**kw):
    return replace(replace(ON, gcode_state=GcodeState.RUNNING, percent=50), **kw)


def test_running_to_finish():
    assert detect(0, running(), replace(running(), gcode_state=GcodeState.FINISH, percent=100)) == [
        Event(0, EventKind.FINISH, "DONE")
    ]


def test_running_to_pause_plain_and_filament():
    assert detect(1, running(), replace(running(), gcode_state=GcodeState.PAUSE)) == [
        Event(1, EventKind.PAUSE, "PAUSED")
    ]
    paused = replace(running(), gcode_state=GcodeState.PAUSE, hms_codes=("0700_2000_0002_0001",))
    assert detect(1, running(), paused) == [Event(1, EventKind.PAUSE, "FILAMENT")]


def test_failed_and_print_error():
    assert detect(2, running(), replace(running(), gcode_state=GcodeState.FAILED)) == [
        Event(2, EventKind.ERROR, "ERROR")
    ]
    errored = replace(running(), print_error=50331904, hms_codes=("0300_0100_0002_0001",))
    assert detect(2, running(), errored) == [Event(2, EventKind.ERROR, "0300_0100_0002_0001")]


def test_error_fires_once_while_error_persists():
    errored = replace(running(), gcode_state=GcodeState.FAILED)
    assert detect(0, errored, replace(errored, percent=51)) == []


def test_no_event_on_first_report():
    fresh = PrinterState(name="A")  # CONNECTING, no report yet
    finished = replace(ON, gcode_state=GcodeState.FINISH, percent=100)
    assert detect(0, fresh, finished) == []
    offline = replace(finished, connection=Connection.OFFLINE)
    assert detect(0, offline, finished) == []  # reconnect must not re-announce


def test_same_state_no_event():
    assert detect(0, running(), running(percent=51)) == []
    assert detect(0, replace(ON, gcode_state=GcodeState.IDLE), replace(ON, gcode_state=GcodeState.IDLE)) == []


def test_idle_to_finish_is_not_announced():
    idle = replace(ON, gcode_state=GcodeState.IDLE)
    assert detect(0, idle, replace(ON, gcode_state=GcodeState.FINISH)) == []


def test_filament_pause_with_print_error_is_pause_not_error():
    paused = replace(running(), gcode_state=GcodeState.PAUSE, print_error=0x0700_2001,
                     hms_codes=("0700_2000_0002_0001",))
    assert detect(0, running(), paused) == [Event(0, EventKind.PAUSE, "FILAMENT")]
    # once resumed with the error code gone, nothing more is announced
    assert detect(0, paused, running()) == []
