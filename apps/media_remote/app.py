"""BUSY Bar media remote: shows what macOS is playing and controls it from the bar.

    python -m apps.media_remote.app                  # USB bar at 10.0.4.20
    python -m apps.media_remote.app --host 127.0.0.1:8080
    python -m apps.media_remote.app --print-only     # dump the current Now Playing state
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from busylib import AsyncBusyBar, exceptions

from apps.bambu_progress.app import configure_logging, wait_for_bar
from apps.bambu_progress.icons import ensure_uploaded
from apps.bambu_progress.ui import parse_input_events

from .controller import SeekAccumulator, back_action, clamp_target
from .icons import kind_for, required_icons
from .lyrics import LyricsCache, line_at
from .nowplaying import IDLE, Bridge, NowPlaying, position
from .render import APP, music_page, render, render_idle, render_music
from .thumbs import ThumbCache, thumb_source

POLL = 1.0
TICK = 0.5
RECONNECT = 5.0
DEFAULT_HOST = "10.0.4.20"
CACHE_DIR = Path.home() / "Library/Caches/busybar-media-remote/thumbs"
LYRICS_DIR = Path.home() / "Library/Caches/busybar-media-remote/lyrics"

log = logging.getLogger("media-remote")


async def _run_inline(fn, *args):
    """Default `run_blocking` for tests: call synchronously, still awaitable."""
    return fn(*args)


class MediaApp:
    def __init__(self, bar: Any, bridge: Bridge, cache: ThumbCache | None, *,
                 lyrics: LyricsCache | None = None,
                 now: Callable[[], float] = time.monotonic,
                 run_blocking: Callable[..., Any] = _run_inline) -> None:
        self.bar = bar
        self.bridge = bridge
        self.cache = cache
        self.lyrics = lyrics
        self.lyrics_lines: list | None = None
        self.now = now
        self._run = run_blocking   # (fn, *args) -> awaitable; asyncio.to_thread in production
        self.np: NowPlaying = IDLE
        self.kind = "generic"
        self.thumb_name: str | None = None
        self.seek = SeekAccumulator()
        self.frame = 0
        self.failures = 0
        self._shown_key: str | None = None      # media key of the frame currently on the bar (None: unknown)
        self._uploaded: set[str] = set()
        self._thumb_task: asyncio.Task | None = None
        self._last_thumb_key: str | None = None

    # -- state ----------------------------------------------------------------
    def position(self) -> float:
        return position(self.np, self.now())

    async def poll_once(self) -> None:
        np = await self._run(self.bridge.info, self.now())
        if np is None:
            self.failures += 1
            return
        self.failures = 0
        changed = np.media_key != self.np.media_key or np.active != self.np.active
        self.np = np
        if changed:
            self.thumb_name = None
            self.lyrics_lines = None
            self.kind = kind_for(np, has_youtube_tab=False)
            await self._refresh_thumbnail(np)
            if self.kind == "music" and self.lyrics is not None and np.active:
                lines = await self._run(self.lyrics.get, np)
                if np.media_key == self.np.media_key:
                    self.lyrics_lines = lines

    async def _refresh_thumbnail(self, np: NowPlaying) -> None:
        if not np.active:
            return
        tabs = await self._run(self.bridge.chrome_tabs) if np.bundle_id != "com.spotify.client" else []
        spotify = await self._run(self.bridge.spotify_artwork_url) if np.bundle_id == "com.spotify.client" else None
        src = thumb_source(np, tabs, spotify)
        self.kind = kind_for(np, has_youtube_tab=bool(src and src[0] == "youtube"))
        if not src or self.cache is None:
            return
        source, key, url = src
        if source == "music":
            raw = await self._run(self.bridge.music_artwork)
            path = await self._run(self.cache.put, key, raw) if raw else None
        else:
            path = await self._run(self.cache.get_or_fetch, key, url)
        if path is None or np.media_key != self.np.media_key:
            return
        name = "thumb_" + re.sub(r"[^A-Za-z0-9_]", "_", key) + ".png"
        if name not in self._uploaded:
            try:
                await self.bar.assets_upload(APP, name, Path(path).read_bytes())
                self._uploaded.add(name)
            except Exception as exc:  # noqa: BLE001
                log.warning("thumbnail upload failed: %s", exc)
                return
        self.thumb_name = name

    # -- input -----------------------------------------------------------------
    async def handle_input(self, kind: str, value: Any) -> None:
        if kind == "encoder":
            if self.np.active:
                self.seek.add(int(value), self.now())
            return
        button = str(value)
        if not self.np.active:
            return
        now = self.now()
        if button in ("ok", "start"):
            pos = self.position()
            # Optimistic flip so the bar reacts instantly; the next poll brings the truth.
            self.np = replace(self.np, elapsed=pos, received_at=now, rate=0.0 if self.np.playing else 1.0)
            await self._run(self.bridge.toggle)
        elif button == "back":
            if back_action(self.position()) == "restart":
                self.np = replace(self.np, elapsed=0.0, received_at=now)
                await self._run(self.bridge.seek, 0.0)
            else:
                await self._run(self.bridge.previous)

    # -- drawing ---------------------------------------------------------------
    async def render_once(self) -> None:
        now = self.now()
        self.frame += 1
        committed = self.seek.take_if_settled(now)
        if committed is not None and self.np.active:
            target = clamp_target(self.position(), committed, self.np.duration)
            self.np = replace(self.np, elapsed=target, received_at=now)
            await self._run(self.bridge.seek, target)
        pending = self.seek.pending(now)
        preview = self.seek.preview_text(pending) if pending is not None else None
        if self.np.active and self.kind == "music":
            has_lyrics = bool(self.lyrics_lines)
            lyric = line_at(self.lyrics_lines, self.position()) if has_lyrics else None
            page = 1 if preview else music_page(self.frame, has_lyrics)
            key = f"{self.np.media_key}#page{page}"     # page switch = full redraw (the "transition")
            elements = render_music(self.np, self.thumb_name, self.position(), preview, self.frame, lyric=lyric, has_lyrics=has_lyrics)
        elif self.np.active:
            key = self.np.media_key
            elements = render(self.np, self.kind, self.thumb_name, self.position(), preview, self.frame)
        else:
            key = "<idle>"
            elements = render_idle(self.frame)
        try:
            if self._shown_key != key:
                await _clear_app(self.bar)
                self._shown_key = key
            await self.bar.display_draw(elements)
        except exceptions.BusyBarAPIError as exc:
            if exc.status_code != 409:
                log.warning("bar API error: %s", exc)
            self._shown_key = None
        except exceptions.BusyBarError as exc:
            log.warning("bar unreachable: %s", exc)
            self._shown_key = None


async def _clear_app(bar: Any) -> None:
    """DELETE our elements; a 400 means the bar has nothing of ours yet, which is fine."""
    try:
        await bar.display_clear(application_name=APP)
    except exceptions.BusyBarAPIError as exc:
        if exc.status_code != 400:
            raise


# -- loops -----------------------------------------------------------------------

async def poll_loop(app: MediaApp) -> None:
    while True:
        await app.poll_once()
        await asyncio.sleep(POLL)


async def render_loop(app: MediaApp) -> None:
    while True:
        await app.render_once()
        await asyncio.sleep(TICK)


async def input_loop(bar: AsyncBusyBar, app: MediaApp) -> None:
    while True:
        try:
            async for message in bar.stream_status_ws():
                if isinstance(message, dict):
                    for kind, value in parse_input_events(message):
                        await app.handle_input(kind, value)
        except exceptions.BusyBarError as exc:
            log.warning("input stream lost (%s); retry in %.0fs", exc, RECONNECT)
        await asyncio.sleep(RECONNECT)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="media-remote", description="macOS Now Playing on a BUSY Bar")
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--token", default=None)
    p.add_argument("--once", action="store_true", help="draw one frame and exit")
    p.add_argument("--print-only", action="store_true", help="print the Now Playing state and exit")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


async def main_async(args: argparse.Namespace) -> None:
    bridge = Bridge()
    if args.print_only:
        np = bridge.info(time.monotonic())
        print(np)
        if np and np.active:
            print("position:", round(position(np, time.monotonic()), 1), "tabs:", len(bridge.chrome_tabs()))
        return
    bar = AsyncBusyBar(args.host, token=args.token)
    app = MediaApp(bar, bridge, ThumbCache(CACHE_DIR), lyrics=LyricsCache(LYRICS_DIR), run_blocking=asyncio.to_thread)
    tasks: list[asyncio.Task] = []
    try:
        version = await wait_for_bar(bar)
        log.info("BUSY Bar at %s, API %s", args.host, version.api_semver or "unknown")
        uploaded = await ensure_uploaded(bar, required_icons(), application_name=APP)
        log.info("icons ready (%d uploaded)", len(uploaded))
        await app.poll_once()
        if args.once:
            await app.render_once()
            return
        tasks = [asyncio.create_task(poll_loop(app)), asyncio.create_task(render_loop(app)), asyncio.create_task(input_loop(bar, app))]
        print(f"{APP} → {args.host}  (Ctrl-C to stop)")
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if not args.once:
            try:
                await bar.display_clear(application_name=APP)
            except Exception:  # noqa: BLE001
                pass
        await bar.aclose()


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    try:
        asyncio.run(main_async(args))
    except exceptions.BusyBarError as exc:
        print(f"BUSY Bar error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
