"""macOS Now Playing via MediaRemote, reached through osascript (JXA) — the only route that still
works for third-party processes since macOS 15.4. Also asks Chrome for its tabs and Spotify for
artwork through the same script so there is a single subprocess boundary."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("media-remote")

CACHE_DIR = Path.home() / "Library/Caches/busybar-media-remote"
SCRIPT_PATH = CACHE_DIR / "np.js"
MUSIC_SCRIPT_PATH = CACHE_DIR / "music_art.applescript"
MUSIC_ART_PATH = CACHE_DIR / "music_art.bin"

# Apple Music hands its artwork over AppleScript only; write it to a file for us to read.
MUSIC_ART_SCRIPT = """on run argv
  set outPath to item 1 of argv
  tell application "Music"
    if not (exists current track) then return "no track"
    set t to current track
    if (count of artworks of t) is 0 then return "no artwork"
    set d to raw data of artwork 1 of t
    set f to open for access POSIX file outPath with write permission
    set eof f to 0
    write d to f
    close access f
    return (format of artwork 1 of t) as text
  end tell
end run
"""
OSASCRIPT_TIMEOUT = 3.0
TABS_TIMEOUT = 8.0   # enumerating every Chrome tab (and the first-time automation prompt) takes longer

# Command codes for MRNowPlayingController.sendCommand (verified on macOS 27: 0/1/2/4/5/24).
CMD_PLAY, CMD_PAUSE, CMD_TOGGLE, CMD_NEXT, CMD_PREVIOUS, CMD_SEEK = 0, 1, 2, 4, 5, 24

JXA_SCRIPT = r"""
ObjC.import('Foundation');
function loadMR() { $.NSBundle.bundleWithPath('/System/Library/PrivateFrameworks/MediaRemote.framework').load; }
function js(v) { try { return (v && !v.isNil()) ? ObjC.unwrap(v) : null; } catch (e) { return null; } }
function info() {
  loadMR();
  const Req = $.NSClassFromString('MRNowPlayingRequest');
  const item = Req.localNowPlayingItem;
  if (!item || item.isNil()) return {active: false};
  const ni = item.nowPlayingInfo;
  const get = k => js(ni.valueForKey(k));
  let app = null, bundle = null;
  try { const p = Req.localNowPlayingPlayerPath; app = js(p.client.displayName); bundle = js(p.client.bundleIdentifier); } catch (e) {}
  let ts = null; try { const t = get('kMRMediaRemoteNowPlayingInfoTimestamp'); if (t) ts = t.toISOString(); } catch (e) {}
  return {active: true, app: app, bundle_id: bundle,
          title: get('kMRMediaRemoteNowPlayingInfoTitle'), artist: get('kMRMediaRemoteNowPlayingInfoArtist'),
          duration: get('kMRMediaRemoteNowPlayingInfoDuration'), elapsed: get('kMRMediaRemoteNowPlayingInfoElapsedTime'),
          rate: get('kMRMediaRemoteNowPlayingInfoPlaybackRate'), timestamp: ts};
}
function send(cmd, opts) {
  loadMR();
  const c = $.NSClassFromString('MRNowPlayingController').localRouteController;
  c.sendCommandOptionsCompletion(cmd, opts ? $(opts) : $(), null);
  delay(0.05);
}
function tabs() {
  const out = [];
  try {
    const chrome = Application('Google Chrome');
    if (!chrome.running()) return out;
    chrome.windows().forEach(w => { w.tabs().forEach(t => { try { out.push([t.url(), t.title()]); } catch (e) {} }); });
  } catch (e) {}
  return out;
}
function spotify() {
  try {
    const s = Application('Spotify');
    if (!s.running()) return {url: null};
    return {url: s.currentTrack().artworkUrl()};
  } catch (e) { return {url: null}; }
}
function run(argv) {
  const mode = argv[0] || 'info';
  if (mode === 'info') return JSON.stringify(info());
  if (mode === 'cmd') { send(parseInt(argv[1], 10)); return 'ok'; }
  if (mode === 'seek') { send(24, {'kMRMediaRemoteOptionPlaybackPosition': parseFloat(argv[1])}); return 'ok'; }
  if (mode === 'tabs') return JSON.stringify(tabs());
  if (mode === 'spotify') return JSON.stringify(spotify());
  return 'unknown mode';
}
"""


@dataclass(frozen=True)
class NowPlaying:
    active: bool
    app_name: str = ""
    bundle_id: str = ""
    title: str = ""
    artist: str = ""
    duration: float = 0.0
    elapsed: float = 0.0
    rate: float = 0.0
    received_at: float = 0.0

    @property
    def media_key(self) -> str:
        return f"{self.title}|{self.artist}"

    @property
    def playing(self) -> bool:
        return self.active and self.rate > 0


IDLE = NowPlaying(active=False)


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_info(text: str, received_at: float) -> NowPlaying | None:
    try:
        d = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    if not d.get("active"):
        return NowPlaying(active=False, received_at=received_at)
    return NowPlaying(
        active=True,
        app_name=str(d.get("app") or ""),
        bundle_id=str(d.get("bundle_id") or ""),
        title=str(d.get("title") or ""),
        artist=str(d.get("artist") or ""),
        duration=_f(d.get("duration")),
        elapsed=_f(d.get("elapsed")),
        rate=_f(d.get("rate")),
        received_at=received_at,
    )


def position(np: NowPlaying, now: float) -> float:
    """Current playback position: the last reported elapsed time, advanced while playing."""
    if not np.active:
        return 0.0
    pos = np.elapsed + max(0.0, now - np.received_at) * np.rate
    if np.duration > 0:
        pos = min(pos, np.duration)
    return max(0.0, pos)


def _ensure_script(path: Path, text: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def run_osascript(args: list[str]) -> str:
    """Runs the JXA script; `music-art <out>` runs the AppleScript artwork exporter instead."""
    env = dict(os.environ, LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8")
    if args[:1] == ["music-art"]:
        _ensure_script(MUSIC_SCRIPT_PATH, MUSIC_ART_SCRIPT)
        cmd = ["osascript", str(MUSIC_SCRIPT_PATH), *args[1:]]
        timeout = TABS_TIMEOUT
    else:
        _ensure_script(SCRIPT_PATH, JXA_SCRIPT)
        cmd = ["osascript", "-l", "JavaScript", str(SCRIPT_PATH), *args]
        timeout = TABS_TIMEOUT if args[:1] == ["tabs"] else OSASCRIPT_TIMEOUT
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"osascript exit {proc.returncode}")
    return proc.stdout.strip()


class Bridge:
    def __init__(self, run: Callable[[list[str]], str] = run_osascript, music_art_path: Path = MUSIC_ART_PATH) -> None:
        self._run = run
        self._music_art_path = music_art_path

    def _safe(self, args: list[str]) -> str | None:
        try:
            return self._run(args)
        except Exception as exc:  # noqa: BLE001 - a flaky osascript must never kill the app
            log.warning("osascript %s failed: %s", args[0], exc)
            return None

    def info(self, now: float) -> NowPlaying | None:
        out = self._safe(["info"])
        return parse_info(out, now) if out is not None else None

    def _cmd(self, code: int) -> None:
        self._safe(["cmd", str(code)])

    def toggle(self) -> None: self._cmd(CMD_TOGGLE)
    def play(self) -> None: self._cmd(CMD_PLAY)
    def pause(self) -> None: self._cmd(CMD_PAUSE)
    def previous(self) -> None: self._cmd(CMD_PREVIOUS)
    def next(self) -> None: self._cmd(CMD_NEXT)

    def seek(self, seconds: float) -> None:
        text = f"{max(0.0, seconds):.3f}".rstrip("0").rstrip(".")
        self._safe(["seek", text or "0"])

    def chrome_tabs(self) -> list[tuple[str, str]]:
        out = self._safe(["tabs"])
        try:
            data = json.loads(out) if out else []
            return [(str(u), str(t)) for u, t in data]
        except (ValueError, TypeError):
            return []

    def music_artwork(self) -> bytes | None:
        """Current Apple Music track's artwork bytes (JPEG/PNG), or None."""
        try:
            self._music_art_path.unlink(missing_ok=True)
        except OSError:
            pass
        out = self._safe(["music-art", str(self._music_art_path)])
        if not out or out.startswith("no "):
            return None
        try:
            data = self._music_art_path.read_bytes()
        except OSError:
            return None
        return data or None

    def spotify_artwork_url(self) -> str | None:
        out = self._safe(["spotify"])
        try:
            url = json.loads(out).get("url") if out else None
            return str(url) if url else None
        except (ValueError, TypeError, AttributeError):
            return None
