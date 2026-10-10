import io

from PIL import Image

from apps.media_remote.nowplaying import NowPlaying
from apps.media_remote.thumbs import ThumbCache, thumb_source, to_thumb_png, youtube_id, youtube_id_for


def test_youtube_id_from_urls():
    assert youtube_id("https://www.youtube.com/watch?v=1nrdU-sxhAo") == "1nrdU-sxhAo"
    assert youtube_id("https://www.youtube.com/watch?v=abc_123&list=PL1&index=3") == "abc_123"
    assert youtube_id("https://youtu.be/xyz789?t=10") == "xyz789"
    assert youtube_id("https://m.youtube.com/watch?app=desktop&v=q1w2e3") == "q1w2e3"
    assert youtube_id("https://www.youtube.com/") is None
    assert youtube_id("https://example.com/watch?v=nope") is None


def test_youtube_id_prefers_title_match():
    tabs = [
        ("https://www.youtube.com/watch?v=first1", "First video - YouTube"),
        ("https://www.youtube.com/watch?v=secnd2", "맥이라 불편하다고요? 앱 12가지 - YouTube"),
        ("https://news.example.com", "News"),
    ]
    assert youtube_id_for("맥이라 불편하다고요? 앱 12가지", tabs) == "secnd2"
    assert youtube_id_for("First video", tabs) == "first1"
    # no title match: fall back to the only tab when there is exactly one, else None
    assert youtube_id_for("Other", tabs) is None
    assert youtube_id_for("Other", tabs[:1]) == "first1"
    assert youtube_id_for("x", []) is None


def _png(w, h, color=(200, 30, 30)):
    buf = io.BytesIO(); Image.new("RGB", (w, h), color).save(buf, "PNG"); return buf.getvalue()


def test_to_thumb_png_crops_and_resizes():
    out = to_thumb_png(_png(120, 90))            # 4:3 -> center crop to 21:16 then resize
    im = Image.open(io.BytesIO(out))
    assert im.size == (21, 16) and im.mode == "RGB"
    assert im.getpixel((10, 8)) == (200, 30, 30)
    out2 = to_thumb_png(_png(300, 300), size=(16, 16))
    assert Image.open(io.BytesIO(out2)).size == (16, 16)


def test_to_thumb_png_rejects_garbage():
    assert to_thumb_png(b"not an image") is None


def test_thumb_cache_fetches_once(tmp_path):
    cache = ThumbCache(tmp_path)
    calls = []
    fetch = lambda url: calls.append(url) or _png(120, 90)
    p1 = cache.get_or_fetch("yt:abc", "https://i.ytimg.com/vi/abc/default.jpg", fetch)
    p2 = cache.get_or_fetch("yt:abc", "https://i.ytimg.com/vi/abc/default.jpg", fetch)
    assert p1 == p2 and p1.exists() and calls == ["https://i.ytimg.com/vi/abc/default.jpg"]
    assert Image.open(p1).size == (21, 16)
    assert cache.get_or_fetch("yt/../x", "u", fetch) is None            # unsafe key
    assert cache.get_or_fetch("yt:bad", "u", lambda u: b"junk") is None  # undecodable
    def boom(u): raise OSError("offline")
    assert cache.get_or_fetch("yt:off", "u", boom) is None


def test_thumb_source_picks_youtube_then_spotify():
    chrome = NowPlaying(active=True, app_name="Google Chrome", bundle_id="com.google.Chrome", title="First video", artist="")
    tabs = [("https://www.youtube.com/watch?v=first1", "First video - YouTube")]
    assert thumb_source(chrome, tabs, None) == ("youtube", "yt:first1", "https://i.ytimg.com/vi/first1/default.jpg")
    spotify = NowPlaying(active=True, app_name="Spotify", bundle_id="com.spotify.client", title="Song", artist="Band")
    assert thumb_source(spotify, [], "https://i.scdn.co/image/abc") == ("spotify", "sp:Song|Band", "https://i.scdn.co/image/abc")
    assert thumb_source(spotify, [], None) is None
    assert thumb_source(chrome, [], None) is None


def test_thumb_cache_put_stores_converted_bytes(tmp_path):
    cache = ThumbCache(tmp_path)
    p = cache.put("am:Song|NF", _png(600, 600, (10, 200, 10)))
    assert p is not None and Image.open(p).size == (21, 16)
    assert cache.put("am:bad", b"junk") is None
    assert cache.path_for("am:Song|NF") == p and p.exists()


def test_thumb_source_apple_music_uses_local_artwork():
    music = NowPlaying(active=True, app_name="음악", bundle_id="com.apple.Music", title="The Search", artist="NF")
    assert thumb_source(music, [], None) == ("music", "am:The Search|NF", "music:artwork")
