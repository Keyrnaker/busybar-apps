from apps.bambu_progress.icons import DIM, TRACK
from apps.bambu_progress.render import rgba
from apps.media_remote.icons import BITMAPS, KIND_COLORS, PLACEHOLDER, icon_filename, kind_for, required_icons
from apps.media_remote.nowplaying import IDLE, NowPlaying
from apps.media_remote.render import format_time, render, render_idle

YT = NowPlaying(active=True, app_name="Google Chrome", bundle_id="com.google.Chrome", title="Short", artist="", duration=574.0, elapsed=287.0, rate=1.0, received_at=0.0)


def by_type(out, kind):
    return [e for e in out.elements if e.type == kind]


def test_bitmaps_and_icons():
    for name in ("youtube", "spotify", "music", "generic"):
        assert len(BITMAPS[name]) == 8 and all(len(r) == 8 for r in BITMAPS[name])
    assert len(BITMAPS["note_big"]) == 12 and all(len(r) == 12 for r in BITMAPS["note_big"])
    icons = required_icons()
    assert {"app_youtube.png", "app_spotify.png", "app_music.png", "app_generic.png", PLACEHOLDER} <= icons.keys()
    assert icon_filename("youtube") == "app_youtube.png"
    assert all(v[:8] == b"\x89PNG\r\n\x1a\n" for v in icons.values())


def test_kind_for():
    assert kind_for(YT, has_youtube_tab=True) == "youtube"
    assert kind_for(YT, has_youtube_tab=False) == "generic"
    assert kind_for(NowPlaying(active=True, bundle_id="com.spotify.client"), False) == "spotify"
    assert kind_for(NowPlaying(active=True, bundle_id="com.apple.Music"), False) == "music"
    assert kind_for(IDLE, False) == "generic"


def test_format_time():
    assert format_time(0) == "0:00"
    assert format_time(401.9) == "6:41"
    assert format_time(3725) == "1:02:05"


def test_render_layout_playing_with_thumb():
    out = render(YT, "youtube", "yt_first1.png", pos=287.0, preview=None, frame=0)
    assert out.application_name == "media-remote"
    imgs = {e.id: e for e in by_type(out, "image")}
    assert (imgs["1"].x, imgs["1"].y, imgs["1"].path) == (0, 4, "app_youtube.png")
    assert (imgs["2"].x, imgs["2"].y, imgs["2"].path) == (9, 0, "yt_first1.png")
    texts = {e.id: e for e in by_type(out, "text")}
    assert texts["3"].text == "Short" and texts["3"].x == 31 and texts["3"].font == "small" and texts["3"].width is None
    assert texts["4"].text == "4:47/9:34" and texts["4"].font == "tiny"
    rects = {e.id: e for e in by_type(out, "rectangle")}
    assert (rects["5"].x, rects["5"].y, rects["5"].width, rects["5"].height, rects["5"].fill_colors[0]) == (31, 14, 41, 2, rgba(TRACK))
    assert (rects["6"].width, rects["6"].fill_colors[0]) == (round(41 * 287 / 574), rgba(KIND_COLORS["youtube"]))


def test_render_title_scrolls_when_long():
    long_np = NowPlaying(active=True, title="A very long video title here", duration=100, elapsed=1, rate=1)
    t = {e.id: e for e in by_type(render(long_np, "generic", None, 1.0, None, 0), "text")}["3"]
    assert t.width == 41 and t.scroll_rate and t.scroll_rate > 0
    img2 = {e.id: e for e in by_type(render(long_np, "generic", None, 1.0, None, 0), "image")}["2"]
    assert img2.path == PLACEHOLDER   # no thumbnail: big note placeholder


def test_render_paused_dims_fill_and_preview_replaces_time():
    paused = NowPlaying(active=True, title="S", duration=100, elapsed=50, rate=0)
    out = render(paused, "spotify", None, 50.0, None, 0)
    rects = {e.id: e for e in by_type(out, "rectangle")}
    assert rects["6"].fill_colors[0] == rgba(KIND_COLORS["spotify"], 0x60)
    out2 = render(paused, "spotify", None, 50.0, "> +30s", 0)
    t4 = {e.id: e for e in by_type(out2, "text")}["4"]
    assert t4.text == "> +30s" and t4.color == rgba(KIND_COLORS["spotify"])
    zero = render(NowPlaying(active=True, title="S", duration=0, elapsed=0, rate=1), "generic", None, 0.0, None, 0)
    assert "6" not in {e.id for e in by_type(zero, "rectangle")}   # unknown duration: track only


def test_render_idle():
    out = render_idle(frame=0)
    imgs = {e.id: e for e in by_type(out, "image")}
    assert imgs["1"].path == "app_generic_dim.png"
    texts = {e.id: e for e in by_type(out, "text")}
    assert "재생" in texts["3"].text and texts["3"].color == rgba(DIM)
    assert by_type(out, "rectangle") == []


def test_render_non_ascii_title_uses_global_font_and_drops_time_line():
    ko = NowPlaying(active=True, title="혼날만했다는 김다현 충격무대", duration=38.8, elapsed=10.0, rate=1.0)
    out = render(ko, "youtube", None, 10.0, None, 0)
    texts = {e.id: e for e in by_type(out, "text")}
    assert texts["3"].font == "global" and texts["3"].y == 7 and texts["3"].width == 41 and texts["3"].scroll_rate   # 12px glyphs centred at y7 -> rows 1..12, nothing clipped
    assert "4" not in texts                                         # no room for the time line under a 12px font
    assert {e.id for e in by_type(out, "rectangle")} == {"5", "6"}  # bar still there
    out2 = render(ko, "youtube", None, 10.0, "> +30s", 0)
    texts2 = {e.id: e for e in by_type(out2, "text")}
    assert "3" not in texts2 and texts2["4"].text == "> +30s" and texts2["4"].font == "small" and texts2["4"].y == 7
    short_ko = render(NowPlaying(active=True, title="안녕", duration=10, elapsed=1, rate=1), "generic", None, 1.0, None, 0)
    assert {e.id: e for e in by_type(short_ko, "text")}["3"].width is None   # short: no scroll


def test_render_idle_uses_global_font_for_korean():
    t = {e.id: e for e in by_type(render_idle(0), "text")}["3"]
    assert t.font == "global" and t.y == 7


def test_render_music_pages_alternate_title_and_time():
    from apps.media_remote.render import MUSIC_PAGE_TICKS, render_music
    am = NowPlaying(active=True, app_name="음악", bundle_id="com.apple.Music", title="The Search", artist="NF", duration=248.1, elapsed=101.7, rate=1.0)
    p0 = render_music(am, "am_thumb.png", 101.7, None, frame=0)
    t0 = {e.id: e for e in by_type(p0, "text")}
    assert t0["3"].text == "The Search" and t0["4"].text == "NF"
    assert {e.id: e.path for e in by_type(p0, "image")} == {"1": "app_music.png", "2": "am_thumb.png"}
    assert by_type(p0, "rectangle") == []
    p1 = render_music(am, "am_thumb.png", 101.7, None, frame=MUSIC_PAGE_TICKS[0])   # first tick of page 2
    t1 = {e.id: e for e in by_type(p1, "text")}
    assert t1["7"].text == "1:41" and t1["7"].font == "small"
    assert t1["8"].text == "/ 4:08" and t1["8"].align == "mid_right" and t1["8"].x == 71
    rects = {e.id: e for e in by_type(p1, "rectangle")}
    assert (rects["5"].y, rects["5"].height) == (10, 5) and rects["6"].width == round(41 * 101.7 / 248.1)
    assert rects["6"].fill_colors[0] == rgba(KIND_COLORS["music"])
    assert "3" not in t1
    # the cycle: page 0 for MUSIC_PAGE_TICKS[0] ticks, then page 1 for MUSIC_PAGE_TICKS[1], then back
    cycle = sum(MUSIC_PAGE_TICKS)
    assert "3" in {e.id for e in by_type(render_music(am, None, 1, None, frame=cycle), "text")}
    # seek preview forces the time page and replaces the time text
    pv = render_music(am, None, 101.7, "> +30s", frame=0)
    tp = {e.id: e for e in by_type(pv, "text")}
    assert tp["7"].text == "> +30s" and "3" not in tp
    # korean artist is skipped on page 0 (tiny font has no Hangul); korean title uses global
    ko = NowPlaying(active=True, bundle_id="com.apple.Music", title="밤편지", artist="아이유", duration=10, elapsed=1, rate=1)
    tk = {e.id: e for e in by_type(render_music(ko, None, 1, None, frame=0), "text")}
    assert tk["3"].font == "global" and "4" not in tk


def test_render_music_with_lyrics_is_static_lyric_over_bar():
    from apps.media_remote.render import MUSIC_PAGE_TICKS, render_music
    am = NowPlaying(active=True, bundle_id="com.apple.Music", title="The Search", artist="NF", duration=248.0, elapsed=40.0, rate=1.0)
    for frame in (0, MUSIC_PAGE_TICKS[0], 999):     # never alternates while lyrics are known
        out = render_music(am, None, 40.0, None, frame=frame, lyric="I don't know, it's alright", has_lyrics=True)
        t = {e.id: e for e in by_type(out, "text")}
        assert t["3"].text == "I don't know, it's alright" and t["3"].font == "small" and t["3"].width == 41
        assert "4" not in t and "7" not in t and "8" not in t          # no artist, no time text
        rects = {e.id: e for e in by_type(out, "rectangle")}
        assert (rects["5"].y, rects["5"].height, rects["5"].width) == (14, 2, 41)
        assert rects["6"].width == round(41 * 40.0 / 248.0)
    ko = render_music(am, None, 40.0, None, frame=0, lyric="이 밤 그날의 반딧불을", has_lyrics=True)
    assert {e.id: e for e in by_type(ko, "text")}["3"].font == "global"
    # lyrics known but no line yet (intro): title on top, bar below, still no alternation
    intro = render_music(am, None, 5.0, None, frame=MUSIC_PAGE_TICKS[0], lyric=None, has_lyrics=True)
    ti = {e.id: e for e in by_type(intro, "text")}
    assert ti["3"].text == "The Search" and "7" not in ti and "5" in {e.id for e in by_type(intro, "rectangle")}
    # seek preview: time page as usual
    pv = render_music(am, None, 40.0, "> +30s", frame=0, lyric="x", has_lyrics=True)
    assert {e.id: e for e in by_type(pv, "text")}["7"].text == "> +30s"
    # no lyrics: the two pages keep alternating
    nol = render_music(am, None, 40.0, None, frame=MUSIC_PAGE_TICKS[0], lyric=None, has_lyrics=False)
    assert "7" in {e.id for e in by_type(nol, "text")}


def test_global_font_text_never_starts_above_row_one():
    from apps.media_remote.render import render_music
    ko = NowPlaying(active=True, title="혼날만했다는 김다현 충격무대", duration=38.8, elapsed=10.0, rate=1.0)
    for out in (render(ko, "youtube", None, 10.0, None, 0), render_music(ko, None, 10.0, None, 0, lyric="이 밤 그날의", has_lyrics=True)):
        t = {e.id: e for e in by_type(out, "text")}["3"]
        assert t.font == "global" and t.y - 6 >= 1, "a 12px glyph anchored mid at y must keep its top row on screen"
