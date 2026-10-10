from apps.steady_clock.app import DIGIT_W, SLOT, elements_for, layout_x


def by_id(elements):
    return {e["id"]: e for e in elements}


def test_slots_are_fixed_and_centered():
    els = elements_for("12:34:56", color="#FFFFFFFF")
    ids = by_id(els)
    xs = [ids[f"t{i}"]["x"] for i in range(8)]
    # 6 digit slots of 8px and 2 colon slots of 4px = 56px, centred: starts at x=8
    assert layout_x("12:34:56") == 8
    assert xs == [8 + 1, 16, 24 + 1, 28, 36, 44 + 1, 48, 56]      # '1' (4px) is centred inside its 7px cell (+1)
    assert all(e["align"] == "mid_left" and e["font"] == "extra_large" for e in ids.values())
    assert ids["t2"]["text"] == ":" and ids["t2"]["x"] == 24 + 1     # colon sits 1px into its 4px slot
    assert ids["t0"]["text"] == "1" and ids["t1"]["text"] == "2"


def test_same_slots_regardless_of_digits():
    a = by_id(elements_for("11:11:11", "#FFFFFFFF"))
    b = by_id(elements_for("00:00:00", "#FFFFFFFF"))
    for i in (1, 4, 7):                                                 # non-1 digit cells keep the same x
        assert a[f"t{i}"]["x"] == b[f"t{i}"]["x"] or a[f"t{i}"]["text"] == "1"
    assert [b[f"t{i}"]["x"] for i in range(8)] == [8, 16, 25, 28, 36, 45, 48, 56]


def test_no_seconds():
    els = elements_for("09:05", "#FF0000FF")
    xs = [e["x"] for e in els]
    assert len(els) == 5 and layout_x("09:05") == (72 - (4 * 8 + 4)) // 2 == 18
    assert xs[0] == 18 and all(e["y"] == 8 for e in els)
    assert all(e["type"] == "text" and e["font"] == "extra_large" for e in els)   # nothing but the time
    assert DIGIT_W == 7 and SLOT == 8
