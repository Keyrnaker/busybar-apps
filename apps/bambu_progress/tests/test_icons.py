import struct
import zlib

import pytest

from apps.bambu_progress.config import PrinterConfig
from apps.bambu_progress.icons import (
    BITMAPS,
    DARK_RED,
    DIM,
    GREEN,
    LIME,
    RED,
    WHITE,
    YELLOW,
    ensure_uploaded,
    icon_filename,
    required_icons,
    to_png,
)


def _decode(png: bytes) -> tuple[int, int, bytes]:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", png[16:24])
    # single IDAT right after IHDR (8 sig + 25 IHDR chunk)
    idat_len = struct.unpack(">I", png[33:37])[0]
    assert png[37:41] == b"IDAT"
    raw = zlib.decompress(png[41 : 41 + idat_len])
    return w, h, raw


def test_all_bitmaps_are_8_rows():
    for name, rows in BITMAPS.items():
        width = 14 if name.startswith("big_") else 7 if "logo" in name else 8   # the Bambu mark is the user's 7x8 drawing
        assert len(rows) == (14 if name.startswith("big_") else 7 if name.startswith("grid_") else 8), name   # grid copies drop one row; big is 2x grid
        assert all(len(r) == width and set(r) <= {"#", ".", "o"} for r in rows), name
    from apps.bambu_progress.icons import DEFAULT_MARK, MARKS
    assert DEFAULT_MARK == "printer" and BITMAPS["logo"] == MARKS["printer"]                     # neutral by default
    assert MARKS["bambu"] == ("###.###", "###.###", "###..##", "###.#.#", "##..##.", "#.#.###", ".##.###", "###.###")   # the hand-drawn option
    assert {"logo", "grid_logo", "check", "pause", "error", "hourglass"} <= BITMAPS.keys()
    assert not any(n.startswith(("logo_run", "grid_logo_run")) for n in BITMAPS)   # run frames are generated (run_frames)


def test_to_png_two_colour_palette():
    bitmap = ("#o......",) + ("........",) * 7
    w, h, raw = _decode(to_png(bitmap, {"#": "#22AA13", "o": "#FFFFFF"}))
    assert raw[1:5] == bytes([0x22, 0xAA, 0x13, 0xFF])
    assert raw[5:9] == bytes([0xFF, 0xFF, 0xFF, 0xFF])
    assert raw[9:13] == bytes([0, 0, 0, 0])


def test_to_png_encodes_pixels_with_alpha():
    bitmap = ("#.......",) + ("........",) * 7
    w, h, raw = _decode(to_png(bitmap, "#3DDC84"))
    assert (w, h) == (8, 8)
    assert raw[0] == 0  # filter byte
    assert raw[1:5] == bytes([0x3D, 0xDC, 0x84, 0xFF])
    assert raw[5:9] == bytes([0, 0, 0, 0])


def test_icon_filename_is_lowercase_hex_with_bitmap_hash():
    import re
    name = icon_filename("check", "#3DDC84")
    assert re.fullmatch(r"check_3ddc84_[0-9a-f]{4}\.png", name), name
    assert icon_filename("check", "#3DDC84") == name                  # stable for the same bitmap
    assert icon_filename("check", "#3DDC84") != icon_filename("error", "#3DDC84")


def test_required_icons_cover_every_accent():
    cfgs = [
        PrinterConfig("A", "1", "S1", "c", "#63E6BE"),
        PrinterConfig("B", "2", "S2", "c", "#FFBF47"),
    ]
    icons = required_icons(cfgs)
    for accent in ("63e6be", "ffbf47"):
        assert any(k.startswith(f"logo_{accent}_") for k in icons)
        assert not any(k.startswith(f"logo_run") for k in icons)            # printing is an animation now
    for color in (DIM, GREEN, YELLOW, RED):
        assert icon_filename("logo", color) in icons and icon_filename("grid_logo", color) in icons
    assert icon_filename("grid_logo", "#63E6BE") in icons
    from apps.bambu_progress.icons import BITMAPS
    assert len(BITMAPS["grid_logo"]) == 7 and BITMAPS["grid_logo"] == BITMAPS["logo"][1:]
    assert icon_filename("hourglass", DIM) in icons
    assert icon_filename("check", GREEN) in icons
    assert icon_filename("check", GREEN) in icons
    assert not any(n.startswith(("printer_", "nozzle_", "dot_", "cross_")) for n in icons)
    assert all(v[:8] == b"\x89PNG\r\n\x1a\n" for v in icons.values())


class FakeBar:
    def __init__(self, listing=None, fail_list=False):
        self.listing = listing or []
        self.fail_list = fail_list
        self.uploaded: list[tuple[str, str, int]] = []
        self.listed: list[str] = []
        self.deleted: list[str] = []

    async def assets_delete(self, application_name):
        self.deleted.append(application_name)
        self.listing = []

    async def storage_list(self, path):
        from busylib import types

        self.listed.append(path)
        if self.fail_list:
            raise RuntimeError("no such dir")
        return types.StorageList(list=self.listing)

    async def assets_upload(self, application_name, filename, data):
        self.uploaded.append((application_name, filename, len(data)))


@pytest.mark.asyncio
async def test_ensure_uploaded_skips_same_size_uploads_rest():
    from busylib import types

    icons = {"a.png": b"x" * 10, "b.png": b"y" * 20, "c.png": b"z" * 30}
    bar = FakeBar(
        listing=[
            types.StorageFileElement(name="a.png", size=10),
            types.StorageFileElement(name="b.png", size=5),
            types.StorageDirElement(name="sub"),
        ]
    )
    uploaded = await ensure_uploaded(bar, icons, application_name="bambu-progress")
    assert uploaded == ["b.png", "c.png"]
    assert bar.listed == ["/ext/user_assets/bambu-progress"]
    assert bar.uploaded == [("bambu-progress", "b.png", 20), ("bambu-progress", "c.png", 30)]


@pytest.mark.asyncio
async def test_ensure_uploaded_uploads_all_when_listing_fails():
    bar = FakeBar(fail_list=True)
    uploaded = await ensure_uploaded(bar, {"a.png": b"1", "b.png": b"22"})
    assert uploaded == ["a.png", "b.png"]


def _pixels(frame: bytes, width: int):
    """BGRA frame -> {(x, y): (r, g, b, a)}"""
    px = {}
    for i in range(0, len(frame), 4):
        b, g, r, a = frame[i:i + 4]
        px[(i // 4) % width, (i // 4) // width] = (r, g, b, a)
    return px


def test_logo_slit_is_column_three_and_run_dot_climbs_it():
    from apps.bambu_progress.icons import SLIT_X, TRAIL_ALPHA, run_frames
    assert SLIT_X == 3 and all(r[3] == "." for r in BITMAPS["logo"][:-1])     # the channel is open (the tip row may close it)
    for name in ("logo", "grid_logo"):
        bitmap = BITMAPS[name]
        frames = run_frames(bitmap, "#00AE42")
        assert len(frames) == len(bitmap)                                      # one row per frame, top to bottom
        rows = []
        for f in frames:
            px = _pixels(f, 7)
            dots = [xy for xy, c in px.items() if c == (255, 255, 255, 255)]
            assert len(dots) == 1 and dots[0][0] == SLIT_X
            rows.append(dots[0][1])
            trail = [xy for xy, c in px.items() if c == (255, 255, 255, TRAIL_ALPHA)]
            assert trail == ([] if dots[0][1] == 0 else [(SLIT_X, dots[0][1] - 1)])   # dim pixel just above the dot
            assert px[(0, 0)] == (0x00, 0xAE, 0x42, 255) and px[(3, 0)][3] in (0, 255, TRAIL_ALPHA)   # ink in the accent colour, gap transparent
        assert rows == list(range(len(bitmap)))                                # runs the whole slit, never stops midway


def test_run_animation_rests_at_the_bottom_before_looping():
    import struct
    from apps.bambu_progress.anim import HEADER_LEN, SECTION_LEN
    from apps.bambu_progress.icons import RUN_HOLD, animation_bytes
    data = animation_bytes("grid_logo_run", "#00AE42")
    records, display_frames = struct.unpack_from("<II", data, 28)
    assert records == 7 and display_frames == 6 + RUN_HOLD                    # 7 rows; the last one is held
    holds = []
    pos = HEADER_LEN + SECTION_LEN
    for _ in range(records):
        holds.append(data[pos + 1])
        pos += 4 + struct.unpack_from("<H", data, pos + 2)[0]
    assert holds == [1] * 6 + [RUN_HOLD]


def test_pulse_frames_breathe_between_two_colours_and_loop_seamlessly():
    from apps.bambu_progress.icons import pulse_frames
    frames = pulse_frames(BITMAPS["grid_logo"], GREEN, LIME, steps=8)
    first = [_pixels(f, 7)[(0, 0)] for f in frames]
    assert first[0] == (0x3D, 0xDC, 0x84, 255) and first[4] == (0x8C, 0xFE, 0x0C, 255)   # a -> b at the half-way point
    assert first[1] == first[7] and first[2] == first[6]                                  # symmetric: no jump at the loop
    assert all(_pixels(f, 7)[(3, 0)] == (0, 0, 0, 0) for f in frames)                     # the slit stays transparent


def test_required_animations_and_filenames():
    from apps.bambu_progress.anim import SIGNATURE
    from apps.bambu_progress.icons import anim_filename, animation_bytes, required_animations
    cfgs = [PrinterConfig("A", "1", "S1", "c", "#63E6BE"), PrinterConfig("B", "2", "S2", "c", "#FFBF47")]
    anims = required_animations(cfgs)
    names = set(anims)
    for accent in ("63e6be", "ffbf47"):
        assert any(n.startswith(f"logo_run_{accent}_") for n in names) and any(n.startswith(f"grid_logo_run_{accent}_") for n in names)
    assert anim_filename("logo_error", RED) in names and anim_filename("grid_logo_error", RED) in names
    assert not any(n.startswith("logo_done") for n in names)                 # finished logo is a static mark
    assert anim_filename("notice_done", GREEN) in names and anim_filename("notice_pause", YELLOW) in names and anim_filename("notice_error", RED) in names
    assert all(n.endswith(".anim") and data.startswith(SIGNATURE) for n, data in anims.items())
    assert anim_filename("logo_run", "#63E6BE") != anim_filename("logo_run", "#FFBF47")
    assert animation_bytes("logo_run", "#63E6BE") is animation_bytes("logo_run", "#63E6BE")   # cached


def test_big_mark_is_the_grid_mark_scaled_two_times():
    from apps.bambu_progress.icons import animation_bytes
    big, grid = BITMAPS["big_logo"], BITMAPS["grid_logo"]
    assert len(big) == 14 and all(len(r) == 14 for r in big)
    assert all(big[2 * y][2 * x] == big[2 * y + 1][2 * x + 1] == grid[y][x] for y in range(7) for x in range(7))
    data = animation_bytes("big_logo_run", "#00D455")
    assert (data[9], data[10]) == (14, 14)                                     # width, height in the .anim header
    assert len(animation_bytes("big_logo_error", "#FF4D4D")) > 0


def test_select_mark_switches_every_size_and_resets_the_animation_cache():
    from apps.bambu_progress.icons import MARKS, animation_bytes, select_mark
    try:
        select_mark("bambu")
        assert BITMAPS["logo"] == MARKS["bambu"] and BITMAPS["grid_logo"] == MARKS["bambu"][1:] and len(BITMAPS["big_logo"]) == 14
        bambu_run = animation_bytes("grid_logo_run", "#00D455")
        select_mark("printer")
        assert BITMAPS["logo"] == MARKS["printer"]
        assert animation_bytes("grid_logo_run", "#00D455") != bambu_run                     # regenerated for the new mark
        with pytest.raises(KeyError):
            select_mark("nope")
    finally:
        select_mark("printer")
