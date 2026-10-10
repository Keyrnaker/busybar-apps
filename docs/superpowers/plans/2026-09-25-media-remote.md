# media_remote Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A BUSY Bar app that shows what macOS is playing (app icon, thumbnail, title, time, progress) and controls it: OK/START play-pause, BACK restart/previous, dial seeks ±10 s.

**Architecture:** Pure modules (parse, position math, seek accumulator, renderer, thumbnail selection) with all I/O injected: one JXA script run through `osascript` (MediaRemote + Chrome tabs + Spotify artwork), `urllib` for thumbnails, Pillow for resizing, busylib `AsyncBusyBar` for drawing and input. Same input parsing and painter discipline as `apps/bambu_progress`.

**Tech Stack:** Python 3.12 (`.venv`), busylib 2.6, Pillow (via `requirements.txt`), pytest. macOS only.

**Spec:** `docs/superpowers/specs/2026-09-25-media-remote-design.md`

## Global Constraints

- Package `apps/media_remote/` runnable as `.venv/bin/python -m apps.media_remote.app [--host H] [--token T] [--once] [--print-only]`.
- Application name on the bar: `media-remote`. Priority 50. Element ids fixed per screen slot: `1` app icon, `2` thumbnail/placeholder, `3` title, `4` time/preview line, `5` track, `6` fill.
- osascript always runs with `LANG=en_US.UTF-8`, timeout 3 s. Never call osascript from unit tests.
- Seek step 10 s per dial detent; commit after 0.8 s without turns. BACK: position > 3 s → seek to 0, else previous track.
- Commit after every task with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` as the last line.

## Review Focus

1. **A paused item whose `ElapsedTime` is stale** must not advance (rate 0) — Task 1 `test_position_paused_holds`.
2. **Two YouTube tabs open** must pick the one whose tab title matches the Now Playing title — Task 2 `test_youtube_id_prefers_title_match`.
3. **Dial turns that accumulate past the end** must clamp to duration and never seek negative — Task 4 `test_seek_clamps`.
4. **Title longer than 41 px** must scroll, short one must not — Task 3 `test_render_title_scrolls_when_long`.
5. **osascript returning garbage** must keep the last good state, not crash — Task 1 `test_parse_info_garbage`.

---

### Task 1: nowplaying.py — JXA bridge, parsing, position, commands

**Files:** Create `apps/media_remote/__init__.py`, `apps/media_remote/nowplaying.py`; Test `apps/media_remote/tests/__init__.py`, `apps/media_remote/tests/test_nowplaying.py`

**Interfaces:**
- `JXA_SCRIPT: str` (modes: `info`, `cmd <n>`, `seek <sec>`, `tabs`, `spotify`)
- `@dataclass(frozen=True) NowPlaying(active: bool, app_name: str = "", bundle_id: str = "", title: str = "", artist: str = "", duration: float = 0.0, elapsed: float = 0.0, rate: float = 0.0, received_at: float = 0.0)`; `IDLE = NowPlaying(active=False)`; `NowPlaying.media_key -> str` (`f"{title}|{artist}"`)
- `parse_info(text: str, received_at: float) -> NowPlaying | None` (None on garbage)
- `position(np: NowPlaying, now: float) -> float`
- `class Bridge: def __init__(self, run: Callable[[list[str]], str] = run_osascript)`, `info(now) -> NowPlaying | None`, `toggle()`, `play()`, `pause()`, `previous()`, `next()`, `seek(seconds: float)`, `chrome_tabs() -> list[tuple[str,str]]`, `spotify_artwork_url() -> str | None`
- `run_osascript(args: list[str]) -> str` writes `JXA_SCRIPT` to `~/Library/Caches/busybar-media-remote/np.js` once and runs `osascript -l JavaScript <file> <args…>` with `LANG=en_US.UTF-8`, timeout 3.

- [ ] Tests (RED), then implement (GREEN), commit `feat(media-remote): MediaRemote bridge, parsing, position math`.

### Task 2: thumbs.py — YouTube/Spotify thumbnails

**Interfaces:** `youtube_id(url) -> str | None`; `youtube_id_for(title, tabs) -> str | None`; `to_thumb_png(data: bytes, size=(21,16)) -> bytes` (Pillow: center-crop to 21:16 then resize, RGB PNG); `class ThumbCache(dir)` with `path_for(key)`, `get_or_fetch(key, url, fetch) -> bytes | None`; `thumb_source(np, tabs, spotify_url) -> tuple[kind, key, url] | None` where kind in youtube/spotify.

- [ ] Tests (RED) → implement → commit `feat(media-remote): thumbnails from YouTube tabs and Spotify`.

### Task 3: icons.py + render.py

**Interfaces:** `KIND_COLORS`, `BITMAPS` (youtube/spotify/music/generic 8×8 + `note_big` 12×12), `kind_for(np, has_youtube_tab) -> str`, `icon_filename(kind)`, `required_icons() -> dict[str, bytes]` (reuses `apps.bambu_progress.icons.to_png`), `format_time(sec)`, `render(np, kind, thumb_path, pos, preview: str | None, frame) -> DisplayElements`, `render_idle(frame) -> DisplayElements`.

- [ ] Tests (RED) → implement → commit `feat(media-remote): app icons and renderer`.

### Task 4: controller.py — seek accumulator, back action, ui state

**Interfaces:** `class SeekAccumulator(step=10.0, settle=0.8)`: `add(delta, now)`, `pending(now) -> float | None` (total while settling), `take_if_settled(now) -> float | None`, `preview_text(total)`; `back_action(pos) -> "restart" | "previous"`; `clamp_target(pos, delta, duration)`.

- [ ] Tests (RED) → implement → commit `feat(media-remote): seek accumulator and back action`.

### Task 5: app.py, manifest, requirements, icon

- Poll loop (1 s) via `asyncio.to_thread(bridge.info)`, thumbnail fetch in thread when media_key changes, input loop (reuse `apps.bambu_progress.ui.parse_input_events`), render loop 0.5 s with fixed ids; `display_clear` when media_key changes; wait_for_bar reuse from bambu app (import).
- `manifest.yaml` (name: Media Remote), `requirements.txt` (pillow), `icon.png` (drawn from the youtube/generic bitmap on a tile).
- [ ] `--print-only` prints the parsed state; `--once` draws one frame. Commit `feat(media-remote): app entry point`.

### Task 6: Device verification

- [ ] With a YouTube video playing in Chrome: run via launcher (menu shows "Media Remote"), read back the frame, press OK/BACK/dial via `bb.input()` and confirm Chrome reacts (position via `--print-only`). Record results, commit.
