"""Scripted fake printers so the whole UI can be seen on the emulator."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import Any

from .bambu import Connection, GcodeState, PrinterState
from .config import COLORS, PrinterConfig

Step = tuple[float, dict[str, Any]]

DEMO_CONFIGS: list[PrinterConfig] = [
    PrinterConfig("P1S-A", "demo", "DEMO1", "", COLORS["mint"]),
    PrinterConfig("P1S-B", "demo", "DEMO2", "", COLORS["amber"]),
    PrinterConfig("X1C", "demo", "DEMO3", "", COLORS["blue"]),
]


def _ramp(start: int, end: int, step: int, task: str, hold: float = 1.0) -> list[Step]:
    return [
        (hold, {"gcode_state": GcodeState.RUNNING, "percent": p, "remaining_min": (100 - p) * 2, "task_name": task})
        for p in range(start, end + 1, step)
    ]


SCENARIOS: list[list[Step]] = [
    _ramp(0, 100, 5, "benchy.3mf")
    + [(10.0, {"gcode_state": GcodeState.FINISH, "percent": 100, "remaining_min": 0}),
       (5.0, {"gcode_state": GcodeState.IDLE, "percent": 0})],
    _ramp(0, 40, 4, "phone_stand.3mf")
    + [(8.0, {"gcode_state": GcodeState.PAUSE, "hms_codes": ("0700_2000_0002_0001",)}),
       (1.0, {"gcode_state": GcodeState.RUNNING, "hms_codes": ()})]
    + _ramp(44, 100, 4, "phone_stand.3mf")
    + [(6.0, {"gcode_state": GcodeState.FINISH, "remaining_min": 0}),
       (4.0, {"gcode_state": GcodeState.IDLE, "percent": 0})],
    _ramp(0, 25, 5, "gear_set_v3_final.3mf")
    + [(15.0, {"gcode_state": GcodeState.FAILED, "print_error": 50331904, "hms_codes": ("0300_0100_0002_0001",)}),
       (5.0, {"gcode_state": GcodeState.IDLE, "print_error": 0, "hms_codes": (), "percent": 0})],
]


class DemoMonitor:
    def __init__(
        self,
        index: int,
        cfg: PrinterConfig,
        queue: "asyncio.Queue[tuple[int, PrinterState]]",
        *,
        steps: Sequence[Step] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        loop: bool = True,
    ) -> None:
        self.index = index
        self.cfg = cfg
        self.queue = queue
        self.steps = list(steps if steps is not None else SCENARIOS[index % len(SCENARIOS)])
        self.sleep = sleep
        self.clock = clock
        self.loop = loop
        self.state = PrinterState(name=cfg.name)

    async def run(self) -> None:
        while True:
            for hold, changes in self.steps:
                self.state = replace(self.state, connection=Connection.ONLINE, last_report_at=self.clock(), **changes)
                self.queue.put_nowait((self.index, self.state))
                await self.sleep(hold)
            if not self.loop:
                return
