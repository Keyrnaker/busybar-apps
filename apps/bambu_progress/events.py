"""Pure transition detection between two PrinterState snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .bambu import Connection, GcodeState, PrinterState

_LIVE = (Connection.ONLINE, Connection.STALE)
_ACTIVE = (GcodeState.RUNNING, GcodeState.PREPARE, GcodeState.PAUSE)


class EventKind(Enum):
    FINISH = "finish"
    PAUSE = "pause"
    ERROR = "error"


@dataclass(frozen=True)
class Event:
    printer_index: int
    kind: EventKind
    message: str


def detect(index: int, prev: PrinterState, new: PrinterState) -> list[Event]:
    # Only compare two live snapshots; a first report or a reconnect is not a transition.
    if prev.connection not in _LIVE or new.connection not in _LIVE:
        return []
    events: list[Event] = []
    changed = prev.gcode_state is not new.gcode_state and prev.gcode_state in _ACTIVE
    # A run-out pause often comes with a non-zero print_error too; it is still a pause.
    if changed and new.gcode_state is GcodeState.PAUSE and new.filament_out():
        return [Event(index, EventKind.PAUSE, "FILAMENT")]
    if not prev.has_error() and new.has_error():
        message = new.hms_codes[0] if new.hms_codes else "ERROR"
        events.append(Event(index, EventKind.ERROR, message))
        return events
    if changed:
        if new.gcode_state is GcodeState.FINISH:
            events.append(Event(index, EventKind.FINISH, "DONE"))
        elif new.gcode_state is GcodeState.PAUSE:
            events.append(Event(index, EventKind.PAUSE, "PAUSED"))
    return events
