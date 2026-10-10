import json

from apps.media_remote.lyrics import LyricsCache, line_at, lrclib_url, parse_lrc
from apps.media_remote.nowplaying import NowPlaying

LRC = """[00:36.97] Hey Nate, how's life?
[00:38.79] I don't know, it's alright
[01:02.5][02:10.00] Repeated chorus line
[ti:ignored metadata]
garbage line without tag
[00:40.60]  
"""


def test_parse_lrc_sorted_with_repeats_and_blank_lines_dropped():
    lines = parse_lrc(LRC)
    assert lines == [(36.97, "Hey Nate, how's life?"), (38.79, "I don't know, it's alright"), (62.5, "Repeated chorus line"), (130.0, "Repeated chorus line")]
    assert parse_lrc("") == [] and parse_lrc("no tags at all") == []


def test_line_at():
    lines = parse_lrc(LRC)
    assert line_at(lines, 10.0) is None                 # before the first line
    assert line_at(lines, 36.97) == "Hey Nate, how's life?"
    assert line_at(lines, 40.0) == "I don't know, it's alright"
    assert line_at(lines, 500.0) == "Repeated chorus line"
    assert line_at([], 5.0) is None


def test_lrclib_url_encodes_query():
    np = NowPlaying(active=True, title="밤편지", artist="IU", duration=254.3)
    url = lrclib_url(np)
    assert url.startswith("https://lrclib.net/api/get?")
    assert "track_name=%EB%B0%A4%ED%8E%B8%EC%A7%80" in url and "artist_name=IU" in url and "duration=254" in url


def test_lyrics_cache_fetches_once_and_caches_misses(tmp_path):
    np = NowPlaying(active=True, title="The Search", artist="NF", duration=248.0)
    calls = []
    def fetch(url):
        calls.append(url)
        return json.dumps({"syncedLyrics": LRC}).encode()
    cache = LyricsCache(tmp_path)
    lines = cache.get(np, fetch)
    assert lines and lines[0] == (36.97, "Hey Nate, how's life?")
    assert cache.get(np, fetch) == lines and len(calls) == 1          # cached
    miss = NowPlaying(active=True, title="Unknown", artist="Nobody", duration=10.0)
    def not_found(url):
        raise OSError("404")
    assert cache.get(miss, not_found) is None
    assert cache.get(miss, fetch) is None and len(calls) == 1          # negative result cached, no refetch
    plain_only = NowPlaying(active=True, title="Plain", artist="X", duration=1.0)
    assert cache.get(plain_only, lambda u: json.dumps({"syncedLyrics": None, "plainLyrics": "la la"}).encode()) is None


def test_lyrics_cache_falls_back_to_search_by_title_and_duration(tmp_path):
    from apps.media_remote.lyrics import lrclib_search_url
    np = NowPlaying(active=True, title="밤편지", artist="아이유", duration=254.0)
    calls = []
    def fetch(url):
        calls.append(url)
        if url.startswith("https://lrclib.net/api/get?"):
            raise OSError("404")
        return json.dumps([
            {"trackName": "밤편지", "artistName": "IU", "duration": 300.0, "syncedLyrics": "[00:01.00] wrong version"},
            {"trackName": "밤편지", "artistName": "IU", "duration": 254.9, "syncedLyrics": "[00:00.34] 이 밤 그날의 반딧불을"},
            {"trackName": "밤편지", "artistName": "X", "duration": 254.0, "syncedLyrics": None},
        ]).encode()
    lines = LyricsCache(tmp_path).get(np, fetch)
    assert lines == [(0.34, "이 밤 그날의 반딧불을")]
    assert calls[1] == lrclib_search_url(np) and "track_name=%EB%B0%A4%ED%8E%B8%EC%A7%80" in calls[1]
