from dataclasses import replace

from apps.media_remote.app import MediaApp
from apps.media_remote.nowplaying import NowPlaying


class FakeBridge:
    def __init__(self, np):
        self.np = np; self.calls = []
    def info(self, now): return replace(self.np, received_at=now)
    def toggle(self): self.calls.append("toggle")
    def previous(self): self.calls.append("previous")
    def seek(self, s): self.calls.append(("seek", round(s, 1)))
    def chrome_tabs(self): return [("https://www.youtube.com/watch?v=vid1", "Song - YouTube")]
    def spotify_artwork_url(self): return None


class FakeBar:
    def __init__(self): self.draws = []; self.clears = 0; self.uploads = []
    async def display_draw(self, el): self.draws.append(el)
    async def display_clear(self, **kw): self.clears += 1
    async def assets_upload(self, app, name, data): self.uploads.append(name)
    async def storage_list(self, p): raise RuntimeError("no listing")


PLAYING = NowPlaying(active=True, app_name="Google Chrome", bundle_id="com.google.Chrome", title="Song", duration=200.0, elapsed=50.0, rate=1.0)


def make(np=PLAYING, now=100.0):
    bridge = FakeBridge(np); bar = FakeBar()
    clock = {"t": now}
    app = MediaApp(bar, bridge, cache=None, now=lambda: clock["t"])
    return app, bridge, bar, clock


async def test_poll_and_toggle_optimistic():
    app, bridge, bar, clock = make()
    await app.poll_once()
    assert app.np.title == "Song" and app.kind == "youtube"
    assert abs(app.position() - 50.0) < 1e-6
    await app.handle_input("button", "ok")
    assert bridge.calls == ["toggle"] and app.np.rate == 0.0          # optimistic pause
    clock["t"] += 5
    assert abs(app.position() - 50.0) < 1e-6                           # paused: holds
    await app.handle_input("button", "start")
    assert app.np.rate == 1.0 and bridge.calls == ["toggle", "toggle"]


async def test_back_restart_vs_previous():
    app, bridge, bar, clock = make()
    await app.poll_once()
    await app.handle_input("button", "back")                                 # pos 50 > 3 -> restart
    assert bridge.calls == [("seek", 0.0)] and app.position() == 0.0
    await app.handle_input("button", "back")                                 # now at 0 -> previous
    assert bridge.calls[-1] == "previous"


async def test_dial_seek_accumulates_then_commits():
    app, bridge, bar, clock = make()
    await app.poll_once()
    await app.handle_input("encoder", 1); await app.handle_input("encoder", 1); await app.handle_input("encoder", 1)
    await app.render_once()
    assert bridge.calls == []                                          # still settling
    texts = {e.id: e.text for e in bar.draws[-1].elements if e.type == "text"}
    assert texts["4"] == "> +30s"
    clock["t"] += 1.0
    await app.render_once()
    assert bridge.calls == [("seek", 81.0)] and abs(app.position() - 81.0) < 1e-6   # 50 + 1 s of playback + 30
    texts = {e.id: e.text for e in bar.draws[-1].elements if e.type == "text"}
    assert texts["4"].startswith("1:21/")


async def test_render_clears_when_media_changes_and_idle():
    app, bridge, bar, clock = make()
    await app.poll_once(); await app.render_once()
    assert bar.clears == 1 and len(bar.draws) == 1                     # first frame clears leftovers
    await app.render_once()
    assert bar.clears == 1
    bridge.np = replace(PLAYING, title="Other")
    await app.poll_once(); await app.render_once()
    assert bar.clears == 2                                             # media changed -> full clear
    bridge.np = NowPlaying(active=False)
    await app.poll_once(); await app.render_once()
    assert bar.clears == 3 and {e.id for e in bar.draws[-1].elements} == {"1", "2", "3"}


async def test_render_ignores_400_on_first_clear_and_still_draws():
    from busylib import exceptions as bexc
    app, bridge, bar, clock = make()

    async def clear_400(**kw):
        bar.clears += 1
        raise bexc.BusyBarAPIError("Bad Request", status_code=400)
    bar.display_clear = clear_400
    await app.poll_once(); await app.render_once()
    assert bar.clears == 1 and len(bar.draws) == 1       # nothing to clear yet is not an error
    await app.render_once()
    assert bar.clears == 1 and len(bar.draws) == 2       # and we do not keep retrying the clear


async def test_apple_music_mode_pages_and_artwork():
    from apps.media_remote.render import MUSIC_PAGE_TICKS
    from apps.media_remote.thumbs import ThumbCache
    import io
    from PIL import Image
    music = NowPlaying(active=True, app_name="음악", bundle_id="com.apple.Music", title="The Search", artist="NF", duration=248.0, elapsed=100.0, rate=1.0)
    bridge = FakeBridge(music)
    buf = io.BytesIO(); Image.new("RGB", (600, 600), (1, 2, 3)).save(buf, "PNG")
    bridge.music_artwork = lambda: buf.getvalue()
    bar = FakeBar(); clock = {"t": 100.0}
    import tempfile
    cache = ThumbCache(tempfile.mkdtemp())
    app = MediaApp(bar, bridge, cache=cache, now=lambda: clock["t"])
    await app.poll_once()
    assert app.kind == "music" and app.thumb_name == "thumb_am_The_Search_NF.png"
    assert bar.uploads == ["thumb_am_The_Search_NF.png"]
    await app.render_once()
    ids0 = {e.id for e in bar.draws[-1].elements}
    assert "3" in ids0 and "7" not in ids0                       # page 0: title
    for _ in range(MUSIC_PAGE_TICKS[0]):
        await app.render_once()
    ids1 = {e.id for e in bar.draws[-1].elements}
    assert "7" in ids1 and "3" not in ids1                       # page 1: time + thick bar
    assert bar.clears == 2                                       # first frame + page switch


async def test_apple_music_fetches_lyrics_and_renders_current_line():
    import tempfile
    from apps.media_remote.lyrics import LyricsCache
    from apps.media_remote.thumbs import ThumbCache
    music = NowPlaying(active=True, bundle_id="com.apple.Music", title="The Search", artist="NF", duration=248.0, elapsed=40.0, rate=1.0)
    bridge = FakeBridge(music); bridge.music_artwork = lambda: None
    bar = FakeBar(); clock = {"t": 100.0}
    lrc = "[00:36.97] Hey Nate\n[00:38.79] Second line\n"
    lyrics = LyricsCache(tempfile.mkdtemp(), fetch=lambda url: ('{"syncedLyrics": %s}' % __import__("json").dumps(lrc)).encode())
    app = MediaApp(bar, bridge, cache=ThumbCache(tempfile.mkdtemp()), lyrics=lyrics, now=lambda: clock["t"])
    await app.poll_once()
    assert app.lyrics_lines and len(app.lyrics_lines) == 2
    await app.render_once()
    t = {e.id: e.text for e in bar.draws[-1].elements if e.type == "text"}
    assert t["3"] == "Second line"
    clears = bar.clears
    for _ in range(30):                                              # lyrics mode never flips pages
        await app.render_once()
    assert bar.clears == clears and "7" not in {e.id for e in bar.draws[-1].elements}
    app.np = replace(app.np, elapsed=5.0, received_at=clock["t"])   # before the first line -> title fallback
    await app.render_once()
    t = {e.id: e.text for e in bar.draws[-1].elements if e.type == "text"}
    assert t["3"] == "The Search"
