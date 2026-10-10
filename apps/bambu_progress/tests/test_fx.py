from apps.bambu_progress import fx
from apps.bambu_progress.anim import LAYOUT_BGR888, SIGNATURE


def _px(frame: bytes, x: int, y: int) -> tuple[int, int, int]:
    i = (y * fx.W + x) * 3
    b, g, r = frame[i:i + 3]
    return r, g, b


def test_notice_frames_are_full_screen_bgr_in_the_theme_colour():
    for kind, (deep, mid, bright) in fx.THEMES.items():
        frames = fx.notice_frames(kind)
        assert len(frames) == fx.FRAMES and all(len(f) == fx.W * fx.H * 3 for f in frames)
        # the far right of the screen is pure backdrop: never black, never brighter than the crest colour
        r, g, b = _px(frames[30], 68, 8)
        assert (r, g, b) != (0, 0, 0)
        dominant = max(range(3), key=lambda i: fx._rgb(mid)[i])
        assert max(range(3), key=lambda i: (r, g, b)[i]) == dominant          # green stays green, red stays red


def test_mark_draws_in_then_fades_before_the_loop():
    frames = fx.notice_frames("done")
    def ink(f):   # rows 1-14 only: the rim on rows 0 and 15 is bright too and moves with the wave
        return sum(1 for x in range(fx.MARK_X, fx.MARK_X + 16) for y in range(1, fx.H - 1) if min(_px(frames[f], x, y)) > 150)
    assert ink(0) < ink(6) < ink(fx.MARK_IN_END)                                # the tick grows
    assert ink(fx.MARK_IN_END) == ink(fx.MARK_OUT_START - 1) > 20               # then stays
    assert ink(fx.FRAMES - 1) < ink(fx.MARK_OUT_START - 1) // 2                 # and fades out before the loop


def test_backdrop_loops_seamlessly():
    theme = fx.THEMES["done"]
    a = fx._backdrop(theme, 0, [])
    b = fx._backdrop(theme, fx.FRAMES, [])
    assert all(abs(a[y][x][i] - b[y][x][i]) < 1e-6 for y in range(fx.H) for x in range(fx.W) for i in range(3))


def test_notice_animation_is_a_bgr888_anim_file():
    data = fx.notice_animation("pause")
    assert data[:8] == SIGNATURE and data[11] == LAYOUT_BGR888 and (data[9], data[10], data[12]) == (fx.W, fx.H, fx.FPS)
    assert len(data) < 400_000


def test_backdrop_follows_the_rounded_bezel_like_the_native_screens():
    frame = fx.notice_frames("done")[30]
    assert all(_px(frame, x, y) == (0, 0, 0) for x in (0, 71) for y in range(16))          # first and last columns dark
    assert all(_px(frame, x, y) == (0, 0, 0) for x in (1, 70) for y in (0, 15))             # top and bottom rows lose one more pixel
    assert _px(frame, 1, 1) != (0, 0, 0) and _px(frame, 2, 0) != (0, 0, 0) and _px(frame, 70, 8) != (0, 0, 0)
    assert len(fx.BEZEL_DARK) == 2 * 16 + 4                                                 # same 36 pixels as indicator_busy_72x16


def test_rim_is_the_lightened_neighbour_and_follows_it():
    frames = fx.notice_frames("done")
    def lum(p): return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]
    # the top rim is brighter than the pixel under it, and moves with it from frame to frame
    diffs = [(lum(_px(f, 30, 0)) - lum(_px(f, 30, 1))) for f in frames[::12]]
    assert all(d > 20 for d in diffs)
    under = [lum(_px(f, 30, 1)) for f in frames[::12]]
    rim = [lum(_px(f, 30, 0)) for f in frames[::12]]
    assert max(under) - min(under) > 10                                        # the wave passes under it...
    assert sorted(range(len(under)), key=under.__getitem__) == sorted(range(len(rim)), key=rim.__getitem__)   # ...and the rim ranks the same way
    f = frames[20]
    assert lum(_px(f, 1, 8)) > lum(_px(f, 2, 8)) and lum(_px(f, 30, 15)) > lum(_px(f, 30, 14))
    assert lum(_px(f, 2, 0)) < lum(_px(f, 3, 0)) * 0.6 and lum(_px(f, 1, 1)) < lum(_px(f, 2, 1)) * 0.6   # rounded corners


def test_detail_backdrop_is_dark_enough_for_text_and_keeps_the_rim():
    for kind in fx.DETAIL_THEMES:
        frames = fx.detail_frames(kind)
        assert len(frames) == fx.DETAIL_FRAMES and all(len(f) == fx.W * fx.H * 3 for f in frames)
        inner = [max(_px(f, x, y)) for f in frames[::8] for y in range(2, 14) for x in range(2, 70)]
        assert max(inner) < 170 and sum(inner) / len(inner) < 80            # never bright behind the text
        assert _px(frames[10], 0, 0) == (0, 0, 0) and _px(frames[10], 30, 0) != (0, 0, 0)   # bezel corners dark, rim lit


def test_enter_ripple_expands_from_the_centre_and_fades_out():
    frames = fx.enter_frames()
    assert len(frames) == fx.ENTER_FRAMES and all(len(f) == fx.W * fx.H * 4 for f in frames)
    def alpha(f, x, y): return f[(y * fx.W + x) * 4 + 3]
    assert alpha(frames[0], 36, 8) > 200                                     # starts bright in the middle
    assert alpha(frames[-1], 36, 8) == 0 and sum(alpha(frames[-1], x, 8) for x in range(fx.W)) < 255   # ends all but clear
    lit = [max(x for x in range(fx.W) if alpha(f, x, 8) > 25) for f in frames[4:9]]   # after the opening flash
    assert lit == sorted(lit) and lit[-1] > lit[0] + 8                       # the ring grows outward
