"""Synced lyrics from LRCLIB (https://lrclib.net), keyed by title/artist/duration, cached on disk."""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .nowplaying import NowPlaying

log = logging.getLogger("media-remote")

USER_AGENT = "busybar-media-remote/0.1 (BUSY Bar app)"
_TAG = re.compile(r"\[(\d+):(\d{2}(?:\.\d+)?)\]")

Line = tuple[float, str]


def parse_lrc(text: str) -> list[Line]:
    lines: list[Line] = []
    for raw in text.splitlines():
        tags = _TAG.findall(raw)
        if not tags:
            continue
        content = _TAG.sub("", raw).strip()
        if not content:
            continue
        for m, s in tags:
            lines.append((int(m) * 60 + float(s), content))
    lines.sort(key=lambda t: t[0])
    return lines


def line_at(lines: list[Line], pos: float) -> str | None:
    current = None
    for t, text in lines:
        if t <= pos:
            current = text
        else:
            break
    return current


def lrclib_url(np: NowPlaying) -> str:
    q = {"artist_name": np.artist, "track_name": np.title, "duration": str(int(round(np.duration)))}
    return "https://lrclib.net/api/get?" + urllib.parse.urlencode(q)


def lrclib_search_url(np: NowPlaying) -> str:
    """Fuzzier fallback: LRCLIB's search by title only (artist names are often romanised differently)."""
    return "https://lrclib.net/api/search?" + urllib.parse.urlencode({"track_name": np.title})


def pick_search_result(results: list, duration: float, tolerance: float = 3.0) -> str | None:
    """The synced lyrics of the candidate whose duration is closest to ours (within tolerance)."""
    best, best_gap = None, tolerance + 1
    for r in results if isinstance(results, list) else []:
        synced = r.get("syncedLyrics") if isinstance(r, dict) else None
        if not synced:
            continue
        try:
            gap = abs(float(r.get("duration") or 0) - duration)
        except (TypeError, ValueError):
            continue
        if gap <= tolerance and gap < best_gap:
            best, best_gap = synced, gap
    return best


def default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=6) as resp:
        return resp.read()


class LyricsCache:
    def __init__(self, directory: Path | str, fetch: Callable[[str], bytes] = default_fetch) -> None:
        self.directory = Path(directory)
        self.fetch = fetch

    def _path(self, np: NowPlaying) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_\-ㄱ-힝]", "_", f"{np.title}_{np.artist}_{int(round(np.duration))}")[:120]
        return self.directory / f"{safe}.json"

    def get(self, np: NowPlaying, fetch: Callable[[str], bytes] | None = None) -> list[Line] | None:
        """Synced lines for the track, or None. Misses are cached too so we do not hammer LRCLIB."""
        if not np.title:
            return None
        path = self._path(np)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                lines = [(float(t), str(s)) for t, s in data.get("lines", [])]
                return lines or None
            except (ValueError, OSError):
                pass
        lines: list[Line] = []
        do_fetch = fetch or self.fetch
        try:
            raw = do_fetch(lrclib_url(np))
            synced = json.loads(raw).get("syncedLyrics")
            lines = parse_lrc(synced) if synced else []
        except Exception as exc:  # noqa: BLE001 - offline/404/garbage all mean "not found here"
            log.info("lyrics exact lookup failed for %s: %s", np.title, exc)
        if not lines:
            try:
                results = json.loads(do_fetch(lrclib_search_url(np)))
                synced = pick_search_result(results, np.duration)
                lines = parse_lrc(synced) if synced else []
            except Exception as exc:  # noqa: BLE001
                log.info("lyrics search failed for %s: %s", np.title, exc)
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(json.dumps({"lines": lines}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return lines or None
