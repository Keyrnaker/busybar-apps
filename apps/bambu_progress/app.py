"""BUSY Bar app: pick a Bambu Lab printer with the dial, watch its progress.

    python -m apps.bambu_progress.app                       # USB bar, printers.toml
    python -m apps.bambu_progress.app --demo                # emulator at 127.0.0.1:8080, fake printers
    python -m apps.bambu_progress.app --host 192.168.1.20 --token 1234
    python -m apps.bambu_progress.app --demo --once         # draw one frame and exit
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
import time
from pathlib import Path

from busylib import AsyncBusyBar, exceptions, types

from .bambu import PrinterMonitor
from .config import ConfigError, load_config
from .demo import DEMO_CONFIGS, DemoMonitor
from .icons import APP, ensure_uploaded, required_animations, required_icons, select_mark
from .ui import Ui, parse_input_events

TICK = 0.5          # seconds between draws (max 2 draws/s)
RECONNECT = 5.0     # seconds before re-opening the bar's input stream
DEMO_HOST = "127.0.0.1:8080"

log = logging.getLogger("bambu-progress")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="bambu-progress", description="Bambu Lab print progress on a BUSY Bar")
    p.add_argument("--host", help="bar address (default: printers.toml or 10.0.4.20; --demo: 127.0.0.1:8080)")
    p.add_argument("--token", help="bar access PIN / API token (overrides printers.toml)")
    p.add_argument("--config", type=Path, default=Path(__file__).resolve().with_name("printers.toml"))
    p.add_argument("--demo", action="store_true", help="fake printers; no printers.toml needed")
    p.add_argument("--once", action="store_true", help="draw one frame and exit")
    p.add_argument("--layout", choices=("list", "grid"), default=None, help="override [display] layout from printers.toml")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


async def wait_for_bar(bar: AsyncBusyBar, *, sleep=asyncio.sleep, interval: float = 5.0):
    """Block until the bar answers /api/version. A bar that is unplugged or still booting is not an
    error to exit on: the launcher may start us before the cable is in."""
    attempt = 0
    while True:
        try:
            return await bar.version()
        except exceptions.BusyBarError as exc:
            attempt += 1
            level = log.warning if attempt in (1, 12) or attempt % 60 == 0 else log.debug
            level("BUSY Bar not reachable (%s); retrying in %.0fs", exc, interval)
            await sleep(interval)


async def input_loop(bar: AsyncBusyBar, ui: Ui) -> None:
    while True:
        try:
            async for message in bar.stream_status_ws():
                if isinstance(message, dict):
                    for kind, value in parse_input_events(message):
                        ui.handle_input(kind, value)
        except exceptions.BusyBarError as exc:
            log.warning("input stream lost (%s); retry in %.0fs", exc, RECONNECT)
        await asyncio.sleep(RECONNECT)


class Painter:
    """Draws frames; removes elements that fell out of the frame without blanking it.

    Firmware keeps every element an app has drawn (upsert by id) and refuses a
    redraw at a lower priority than the frame it currently owns. Ids that a new
    frame no longer sends are deleted individually, so the rest of the screen
    stays put (no flicker when the dial highlight moves or expires). A full
    DELETE for the app is only done when the priority changes (notice <-> main):
    that is the one case where the priority the old frame held must be released.
    """

    def __init__(self, bar: AsyncBusyBar) -> None:
        self.bar = bar
        self.shown: set[str] | None = None  # None: unknown (a previous run may have left elements)
        self.priority: int | None = None
        self._sent: dict[str, Any] = {}     # what the bar holds, by id (elements compare by value)
        self._rejected = False

    @staticmethod
    def _probe(elements: list) -> Any | None:
        """An element that can be re-sent without visible effect: a rectangle or non-scrolling text."""
        for e in elements:
            if e.type == "rectangle" or (e.type == "text" and not getattr(e, "scroll_rate", None)):
                return e
        return None

    async def _clear(self, element_ids: list[str] | None = None) -> None:
        try:
            if element_ids is None:
                await self.bar.display_clear(application_name=APP)
            else:
                await self.bar.display_clear(application_name=APP, element_ids=element_ids)
        except exceptions.BusyBarAPIError as exc:
            if exc.status_code != 400:   # 400: the bar holds nothing of ours yet
                raise

    async def paint(self, elements: types.DisplayElements | None) -> None:
        if elements is None:
            if self.shown is None or self.shown:
                await self.bar.display_clear(application_name=APP)
                self.shown = set()
                self.priority = None
                self._sent = {}
            return
        ids = {e.id for e in elements.elements}
        if self.shown is None or (self.priority is not None and elements.priority != self.priority):
            await self._clear()
            self._sent = {}
            self.shown = set()
        # Re-sending an animation element restarts it from its first frame, so only send what changed.
        # Every element carries an explicit z_index (render.py), so in-place updates keep their place.
        changed = [e for e in elements.elements if self._sent.get(e.id) != e]
        gone = set(self.shown - ids) if self.shown else set()
        # An element cannot change type under its id (the firmware refuses or ignores it), and screens
        # at the same priority reuse ids for different kinds: delete those first, then draw them fresh.
        retyped = {e.id for e in changed if e.id in self._sent and self._sent[e.id].type != e.type}
        if gone or retyped:
            await self._clear(sorted(gone | retyped))
        # If nothing changed, still send one harmless element: that keeps the 409 detection below alive.
        if not changed:
            probe = self._probe(elements.elements)
            changed = [probe] if probe is not None else list(elements.elements)
        try:
            await self.bar.display_draw(elements.model_copy(update={"elements": changed}))
        except exceptions.BusyBarAPIError as exc:
            if exc.status_code != 409:
                raise
            # Another app owns the screen at a higher priority, or our own frame is
            # stuck at a higher one. Forget what we think is shown so the next tick
            # releases the frame and redraws from scratch.
            if not self._rejected:
                log.warning("draw rejected (409): screen owned by a higher priority; will retry")
            self._rejected = True
            self.shown = None
            self._sent = {}
            return
        if self._rejected:
            log.info("draw accepted again")
        self._rejected = False
        self.shown = ids
        self.priority = elements.priority
        self._sent = {e.id: e for e in elements.elements}


async def render_loop(bar: AsyncBusyBar, ui: Ui, queue: asyncio.Queue, *, once: bool = False) -> None:
    painter = Painter(bar)
    while True:
        while not queue.empty():
            index, state = queue.get_nowait()
            ui.apply_update(index, state)
        now = time.monotonic()
        ui.tick(now)
        try:
            await painter.paint(ui.render(now))
            sound = ui.pop_sound()
            if sound:
                await bar.audio_play(stock_path=sound, application_name=APP)
        except exceptions.BusyBarError as exc:
            log.warning("bar unreachable: %s", exc)
        if once:
            return
        await asyncio.sleep(TICK)


async def main_async(args: argparse.Namespace) -> None:
    if args.demo:
        configs, host, token, layout = DEMO_CONFIGS, args.host or DEMO_HOST, args.token, "list"
    else:
        cfg = load_config(args.config)
        configs, host, token, layout = cfg.printers, args.host or cfg.host, args.token or cfg.token, cfg.layout
        select_mark(cfg.mark)
    layout = args.layout or layout

    queue: asyncio.Queue = asyncio.Queue()
    ui = Ui(configs, layout=layout)
    bar = AsyncBusyBar(host, token=token)
    tasks: list[asyncio.Task] = []
    try:
        version = await wait_for_bar(bar)
        log.info("BUSY Bar at %s, API %s", host, version.api_semver or "unknown")
        uploaded = await ensure_uploaded(bar, {**required_icons(configs), **required_animations(configs)})
        log.info("icons ready (%d uploaded)", len(uploaded))

        monitor_cls = DemoMonitor if args.demo else PrinterMonitor
        tasks = [asyncio.create_task(monitor_cls(i, c, queue).run(), name=c.name) for i, c in enumerate(configs)]
        if args.once:
            await asyncio.sleep(1.0)
            await render_loop(bar, ui, queue, once=True)
            return
        tasks.append(asyncio.create_task(input_loop(bar, ui), name="input"))
        tasks.append(asyncio.create_task(render_loop(bar, ui, queue), name="render"))
        print(f"{APP} → {'demo' if args.demo else f'{len(configs)} printers'} on {host}  (Ctrl-C to stop)")
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if not args.once:
            with contextlib.suppress(Exception):
                await bar.display_clear(application_name=APP)
        await bar.aclose()


def configure_logging(verbose: bool) -> None:
    """INFO for this app; busylib/httpx only speak up on problems unless -v."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger().setLevel(level)
    for noisy in ("busylib", "httpx2", "httpcore2", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.DEBUG if verbose else logging.WARNING)


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    try:
        asyncio.run(main_async(args))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        sys.exit(2)
    except exceptions.BusyBarError as exc:
        print(f"BUSY Bar error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
