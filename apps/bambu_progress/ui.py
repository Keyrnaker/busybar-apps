"""Screen state machine: list / detail / hidden plus a notice overlay queue."""
from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
import time
from collections.abc import Callable
from typing import Any

from busylib import types

from .bambu import PrinterState
from .config import PrinterConfig
from .events import Event, EventKind, detect
from .fx import ENTER_SECONDS
from .render import display_order, render_detail, render_grid, render_list, render_notice

NOTICE_SECONDS = 8.0
NOTICE_ALTERNATE = 4.0     # a notice shows its word (DONE / PAUSE / ERROR) and the printer's name in turns
HIGHLIGHT_SECONDS = 10.0   # dial highlight (border) stays this long after the last turn, then selection resets

SOUNDS: dict[EventKind, str] = {
    EventKind.FINISH: "busy/sounds/session_completed.snd",
    EventKind.PAUSE: "shared/sounds/calendar_reminder_ends.snd",
    EventKind.ERROR: "shared/sounds/calendar_event_starts.snd",
}


class Screen(Enum):
    LIST = "list"
    DETAIL = "detail"
    HIDDEN = "hidden"


@dataclass
class Notice:
    event: Event
    until: float | None  # None: stays until a button press
    started: float = 0.0


class Ui:
    def __init__(self, configs: Sequence[PrinterConfig], *, now: Callable[[], float] = time.monotonic, layout: str = "list") -> None:
        self._now = now
        self.layout = layout
        self.configs = list(configs)
        self.states: list[PrinterState] = [PrinterState(name=c.name) for c in self.configs]
        self.screen = Screen.LIST
        self.selected = 0
        self.queue: deque[Event] = deque()
        self.active: Notice | None = None
        self.frame = 0
        self._sound: str | None = None
        self.highlight_until: float | None = None
        self.detail_entered: float | None = None   # when OK opened the detail screen (plays the ripple for ENTER_SECONDS)

    # -- updates from monitors -------------------------------------------------
    def apply_update(self, index: int, state: PrinterState) -> list[Event]:
        prev = self.states[index]
        self.states[index] = state
        events = detect(index, prev, state)
        for event in events:
            if self._is_pending(event):
                continue
            self.queue.append(event)
        return events

    def _is_pending(self, event: Event) -> bool:
        def same(e: Event) -> bool:
            return e.printer_index == event.printer_index and e.kind == event.kind

        if self.active is not None and same(self.active.event):
            return True
        return any(same(e) for e in self.queue)

    # -- display order ---------------------------------------------------------
    def order(self) -> list[int]:
        """Printer indexes in the order the list shows them (attention, printing, done, idle, offline)."""
        return display_order(self.states, self._now())

    def highlight_active(self) -> bool:
        return self.highlight_until is not None and self._now() < self.highlight_until

    # -- input from the bar ----------------------------------------------------
    def handle_input(self, kind: str, value: Any) -> None:
        if self.active is not None:
            self.active = None  # any input just dismisses the notice
            return
        if kind == "encoder":
            if self.screen is Screen.HIDDEN:
                self.screen = Screen.LIST
                return
            order = self.order()
            if not self.highlight_active():
                self.selected = order[0]          # first turn: show the highlight on the top entry, do not move yet
            else:
                position = order.index(self.selected) if self.selected in order else 0
                self.selected = order[(position + int(value)) % len(order)]
            self.highlight_until = self._now() + HIGHLIGHT_SECONDS
            return
        button = str(value)
        if button == "start":
            button = "ok"  # START does the same as OK: open the selected printer
        if button == "ok" and not self.highlight_active() and self.screen is Screen.LIST:
            self.selected = self.order()[0]       # nothing highlighted: OK opens the top entry
        if self.screen is Screen.HIDDEN:
            self.screen = Screen.LIST
        elif self.screen is Screen.LIST:
            if button == "ok":
                self.screen = Screen.DETAIL
                self.detail_entered = self._now()
            elif button == "back":
                self.screen = Screen.HIDDEN
        elif self.screen is Screen.DETAIL:
            if button == "back":
                self.screen = Screen.LIST

    # -- time ------------------------------------------------------------------
    def tick(self, now: float) -> None:
        self.frame += 1
        if self.highlight_until is not None and now >= self.highlight_until:
            self.highlight_until = None
            order = self.order()
            if order:
                self.selected = order[0]
        if self.active is not None and self.active.until is not None and now >= self.active.until:
            self.active = None
        if self.active is None and self.queue:
            event = self.queue.popleft()
            until = None if event.kind is EventKind.ERROR else now + NOTICE_SECONDS
            self.active = Notice(event, until, now)
            self._sound = SOUNDS[event.kind]

    def pop_sound(self) -> str | None:
        sound, self._sound = self._sound, None
        return sound

    # -- output ----------------------------------------------------------------
    def render(self, now: float) -> types.DisplayElements | None:
        if self.active is not None:
            ev = self.active.event
            show_name = int((now - self.active.started) // NOTICE_ALTERNATE) % 2 == 1
            return render_notice(ev, self.configs[ev.printer_index], show_name=show_name)
        if self.screen is Screen.HIDDEN:
            return None
        if self.screen is Screen.DETAIL:
            entering = self.detail_entered is not None and now < self.detail_entered + ENTER_SECONDS
            return render_detail(self.states[self.selected], self.configs[self.selected], now, self.frame, entering=entering)
        return self._render_overview(now, None)

    def _render_overview(self, now: float, order: list[int] | None) -> types.DisplayElements:
        """The list or grid; `order` overrides the live sort (used while the old screen collapses)."""
        order = order if order is not None else self.order()
        highlight = self.highlight_active()
        if self.layout == "grid":
            return render_grid(self.states, self.configs, self.selected, now, self.frame, order=order, highlight=highlight)
        return render_list(self.states, self.configs, self.selected, now, self.frame, order=order, highlight=highlight)


def parse_input_events(message: dict[str, Any]) -> list[tuple[str, Any]]:
    """Same shape the community home-assistant app reads from stream_status_ws."""
    events: list[tuple[str, Any]] = []
    for update in message.get("updates", []) if isinstance(message, dict) else []:
        inp = update.get("input") if isinstance(update, dict) else None
        if not isinstance(inp, dict):
            continue
        button = inp.get("button_event")
        if isinstance(button, dict) and str(button.get("action", "")).lower() in ("", "press"):
            events.append(("button", str(button.get("button") or "ok").lower()))
        encoder = inp.get("encoder_event")
        if isinstance(encoder, dict):
            try:
                delta = int(encoder.get("delta", 0))
            except (TypeError, ValueError):
                delta = 0
            if delta:
                events.append(("encoder", delta))
    return events
