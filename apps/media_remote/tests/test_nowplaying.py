import json

from apps.media_remote.nowplaying import IDLE, Bridge, NowPlaying, parse_info, position

SAMPLE = {
    "active": True, "app": "Google Chrome", "bundle_id": "com.google.Chrome",
    "title": "맥이라 불편하다고요? 앱 12가지 / 오목교 전자상가", "artist": "오목교 전자상가",
    "duration": 574.261, "elapsed": 401.87, "rate": 1, "timestamp": None,
}


def test_parse_info_active_korean():
    np = parse_info(json.dumps(SAMPLE), received_at=100.0)
    assert np.active and np.app_name == "Google Chrome" and np.bundle_id == "com.google.Chrome"
    assert np.title.startswith("맥이라") and np.artist == "오목교 전자상가"
    assert np.duration == 574.261 and np.elapsed == 401.87 and np.rate == 1.0
    assert np.received_at == 100.0
    assert np.media_key == f"{np.title}|{np.artist}"


def test_parse_info_inactive_and_missing_fields():
    assert parse_info(json.dumps({"active": False}), received_at=1.0) == NowPlaying(active=False, received_at=1.0)
    np = parse_info(json.dumps({"active": True, "title": None, "duration": None, "rate": None}), received_at=2.0)
    assert np.active and np.title == "" and np.duration == 0.0 and np.rate == 0.0


def test_parse_info_garbage():
    assert parse_info("execution error: something", received_at=0) is None
    assert parse_info("", received_at=0) is None
    assert parse_info("[1,2]", received_at=0) is None


def test_position_advances_only_while_playing():
    playing = parse_info(json.dumps(SAMPLE), received_at=100.0)
    assert position(playing, now=100.0) == 401.87
    assert abs(position(playing, now=110.0) - 411.87) < 1e-6
    assert position(playing, now=10_000.0) == 574.261  # clamped to duration


def test_position_paused_holds():
    paused = parse_info(json.dumps(dict(SAMPLE, rate=0)), received_at=100.0)
    assert position(paused, now=500.0) == 401.87
    assert position(IDLE, now=5.0) == 0.0


def test_bridge_sends_commands_and_parses_tabs():
    calls = []

    def fake_run(args):
        calls.append(args)
        if args[0] == "info": return json.dumps(SAMPLE)
        if args[0] == "tabs": return json.dumps([["https://www.youtube.com/watch?v=abc123", "Video A - YouTube"], ["https://example.com", "Ex"]])
        if args[0] == "spotify": return json.dumps({"url": "https://i.scdn.co/image/xyz"})
        return "ok"

    b = Bridge(run=fake_run)
    assert b.info(now=7.0).received_at == 7.0
    b.toggle(); b.play(); b.pause(); b.previous(); b.next(); b.seek(12.5)
    assert calls[1:] == [["cmd", "2"], ["cmd", "0"], ["cmd", "1"], ["cmd", "5"], ["cmd", "4"], ["seek", "12.5"]]
    assert b.chrome_tabs() == [("https://www.youtube.com/watch?v=abc123", "Video A - YouTube"), ("https://example.com", "Ex")]
    assert b.spotify_artwork_url() == "https://i.scdn.co/image/xyz"


def test_bridge_tolerates_failures():
    def failing(args):
        raise RuntimeError("osascript timed out")
    b = Bridge(run=failing)
    assert b.info(now=1.0) is None
    assert b.chrome_tabs() == []
    assert b.spotify_artwork_url() is None
    b.toggle()  # must not raise


def test_bridge_seek_formats_zero_and_fractions():
    calls = []
    b = Bridge(run=lambda a: calls.append(a) or "ok")
    b.seek(0); b.seek(0.0); b.seek(300.0); b.seek(12.3456)
    assert calls == [["seek", "0"], ["seek", "0"], ["seek", "300"], ["seek", "12.346"]]


def test_bridge_music_artwork_reads_file_written_by_applescript(tmp_path):
    art = tmp_path / "art.bin"
    def fake_run(args):
        if args[0] == "music-art":
            art.write_bytes(b"\xff\xd8jpeg")
            return "JPEG picture"
        return "ok"
    b = Bridge(run=fake_run, music_art_path=art)
    assert b.music_artwork() == b"\xff\xd8jpeg"
    def no_art(args): return "no artwork"
    assert Bridge(run=no_art, music_art_path=tmp_path / "none.bin").music_artwork() is None
