from apps.media_remote.controller import SeekAccumulator, back_action, clamp_target


def test_seek_accumulates_and_settles():
    acc = SeekAccumulator(step=10.0, settle=0.8)
    assert acc.pending(now=0.0) is None
    acc.add(1, now=0.0)
    acc.add(1, now=0.3)
    acc.add(-1, now=0.5)
    assert acc.pending(now=0.6) == 10.0
    assert acc.preview_text(10.0) == "> +10s" and acc.preview_text(-30.0) == "< -30s"
    assert acc.take_if_settled(now=1.0) is None      # last turn at 0.5, settle at 1.3
    assert acc.take_if_settled(now=1.31) == 10.0
    assert acc.pending(now=1.4) is None               # consumed
    assert acc.take_if_settled(now=2.0) is None


def test_seek_clamps():
    assert clamp_target(pos=574.0, delta=30.0, duration=574.3) == 574.3
    assert clamp_target(pos=5.0, delta=-30.0, duration=574.3) == 0.0
    assert clamp_target(pos=100.0, delta=-30.0, duration=0.0) == 70.0   # unknown duration: no upper clamp
    assert clamp_target(pos=100.0, delta=30.0, duration=0.0) == 130.0


def test_back_action():
    assert back_action(pos=0.0) == "previous"
    assert back_action(pos=2.9) == "previous"
    assert back_action(pos=3.1) == "restart"
