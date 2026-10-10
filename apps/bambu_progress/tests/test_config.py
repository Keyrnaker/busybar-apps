import pytest

from apps.bambu_progress.config import COLORS, ConfigError, load_config, parse_config

GOOD = {
    "busybar": {"host": "10.0.4.20", "token": ""},
    "printers": [
        {"name": "P1S-A", "ip": "192.168.0.31", "serial": "01P00A123456789", "access_code": "12345678", "color": "mint"},
        {"name": "X1C", "ip": "192.168.0.32", "serial": "00M00A123456789", "access_code": "87654321", "color": "amber"},
    ],
}


def test_parse_config_resolves_colors_and_token():
    cfg = parse_config(GOOD)
    assert cfg.host == "10.0.4.20"
    assert cfg.token is None  # empty string becomes None
    assert [p.name for p in cfg.printers] == ["P1S-A", "X1C"]
    assert cfg.printers[0].color == COLORS["mint"]


def test_parse_config_defaults_host_and_color():
    data = {"printers": [{"name": "A", "ip": "1.2.3.4", "serial": "S1", "access_code": "1"},
                         {"name": "B", "ip": "1.2.3.5", "serial": "S2", "access_code": "2"}]}
    cfg = parse_config(data)
    assert cfg.host == "10.0.4.20"
    assert cfg.printers[0].color == cfg.printers[1].color == COLORS["bambu"] == "#00D455"   # one colour for all


def test_parse_config_missing_field_names_location():
    data = {"printers": [GOOD["printers"][0], {"name": "B", "ip": "1.2.3.4", "serial": "S2"}]}
    with pytest.raises(ConfigError, match=r"printers\[1\]\.access_code missing"):
        parse_config(data)


def test_parse_config_rejects_unknown_color():
    data = {"printers": [dict(GOOD["printers"][0], color="purple")]}
    with pytest.raises(ConfigError, match=r"printers\[0\]\.color"):
        parse_config(data)


def test_parse_config_rejects_duplicate_serial():
    data = {"printers": [GOOD["printers"][0], dict(GOOD["printers"][1], serial="01P00A123456789")]}
    with pytest.raises(ConfigError, match="duplicate serial"):
        parse_config(data)


def test_parse_config_rejects_empty_printer_list():
    with pytest.raises(ConfigError, match="at least one printer"):
        parse_config({"printers": []})


def test_load_config_reads_toml(tmp_path):
    path = tmp_path / "printers.toml"
    path.write_text(
        '[busybar]\nhost = "1.1.1.1"\ntoken = "1234"\n\n'
        '[[printers]]\nname = "A"\nip = "1.2.3.4"\nserial = "S1"\naccess_code = "x"\ncolor = "blue"\n'
    )
    cfg = load_config(path)
    assert cfg.host == "1.1.1.1"
    assert cfg.token == "1234"
    assert cfg.printers[0].color == COLORS["blue"]


def test_load_config_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_display_layout_option():
    assert parse_config(GOOD).layout == "list"
    assert parse_config(dict(GOOD, display={"layout": "grid"})).layout == "grid"
    with pytest.raises(ConfigError, match=r"display\.layout"):
        parse_config(dict(GOOD, display={"layout": "huge"}))


def test_parse_config_mark_defaults_to_printer_and_validates():
    cfg = parse_config(GOOD)
    assert cfg.mark == "bambu"
    assert parse_config({**GOOD, "display": {"layout": "grid", "mark": "printer"}}).mark == "printer"
    with pytest.raises(ConfigError):
        parse_config({**GOOD, "display": {"mark": "octopus"}})
