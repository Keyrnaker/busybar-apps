"""Thumbnails: YouTube (via the Chrome tab that matches the Now Playing title) and Spotify artwork.
MediaRemote itself hands third parties no artwork, so this is the only way to get a picture."""
from __future__ import annotations

import io
import logging
import re
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

from .nowplaying import NowPlaying

log = logging.getLogger("media-remote")

THUMB_SIZE = (21, 16)
_YT_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com")
_SAFE_KEY = re.compile(r"^[A-Za-z0-9:_\-|. ㄱ-힝]+$")


def youtube_id(url: str) -> str | None:
    try:
        u = urlparse(url)
    except ValueError:
        return None
    if u.netloc == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
        return vid or None
    if u.netloc in _YT_HOSTS and u.path == "/watch":
        vid = parse_qs(u.query).get("v", [None])[0]
        return vid or None
    return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().casefold()


def youtube_id_for(title: str, tabs: list[tuple[str, str]]) -> str | None:
    """The video id of the YouTube tab whose title is '<title> - YouTube'; a lone YouTube tab otherwise."""
    yt = [(youtube_id(u), t) for u, t in tabs if youtube_id(u)]
    if not yt:
        return None
    want = _norm(title)
    if want:
        for vid, tab_title in yt:
            tt = _norm(tab_title)
            if tt == want or tt.startswith(want) or tt.startswith(f"{want} - youtube") or tt.rstrip(" - youtube") == want:
                return vid
    return yt[0][0] if len(yt) == 1 else None


def to_thumb_png(data: bytes, size: tuple[int, int] = THUMB_SIZE) -> bytes | None:
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:  # noqa: BLE001 - any undecodable payload
        return None
    w, h = im.size
    tw, th = size
    target_ratio = tw / th
    if w / h > target_ratio:                     # too wide: crop sides
        nw = int(round(h * target_ratio)); left = (w - nw) // 2
        im = im.crop((left, 0, left + nw, h))
    else:                                        # too tall: crop top/bottom
        nh = int(round(w / target_ratio)); top = (h - nh) // 2
        im = im.crop((0, top, w, top + nh))
    im = im.resize(size, Image.LANCZOS)
    out = io.BytesIO(); im.save(out, "PNG"); return out.getvalue()


def default_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "busybar-media-remote"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read()


class ThumbCache:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def path_for(self, key: str) -> Path | None:
        if not _SAFE_KEY.match(key) or ".." in key:
            return None
        safe = re.sub(r"[^A-Za-z0-9_\-]", "_", key)
        return self.directory / f"{safe}.png"

    def put(self, key: str, raw: bytes) -> Path | None:
        """Store already-obtained image bytes (e.g. Apple Music artwork) under `key`."""
        path = self.path_for(key)
        if path is None:
            return None
        png = to_thumb_png(raw)
        if png is None:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        return path

    def get_or_fetch(self, key: str, url: str, fetch: Callable[[str], bytes] = default_fetch) -> Path | None:
        path = self.path_for(key)
        if path is None:
            return None
        if path.exists():
            return path
        try:
            raw = fetch(url)
        except Exception as exc:  # noqa: BLE001
            log.info("thumbnail fetch failed for %s: %s", key, exc)
            return None
        png = to_thumb_png(raw)
        if png is None:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png)
        return path


def thumb_source(np: NowPlaying, tabs: list[tuple[str, str]], spotify_url: str | None) -> tuple[str, str, str] | None:
    """(kind, cache key, image url) for the current item, or None when no picture is available."""
    if not np.active:
        return None
    if np.bundle_id == "com.spotify.client":
        return ("spotify", f"sp:{np.media_key}", spotify_url) if spotify_url else None
    if np.bundle_id == "com.apple.Music":
        return ("music", f"am:{np.media_key}", "music:artwork")   # pseudo-url: fetched locally via AppleScript
    vid = youtube_id_for(np.title, tabs)
    if vid:
        return ("youtube", f"yt:{vid}", f"https://i.ytimg.com/vi/{vid}/default.jpg")
    return None
