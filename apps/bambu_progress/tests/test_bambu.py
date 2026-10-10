from dataclasses import replace

from apps.bambu_progress.bambu import (
    PUSHALL_EVERY,
    STALE_AFTER,
    Connection,
    GcodeState,
    PrinterState,
    effective_connection,
    hms_code,
    parse_report,
)

BASE = PrinterState(name="P1S-A")

FULL = {
    "print": {
        "gcode_state": "RUNNING",
        "mc_percent": 42,
        "mc_remaining_time": 75,
        "subtask_name": "benchy.3mf",
        "print_error": 0,
        "hms": [],
        "layer_num": 120,
        "total_layer_num": 340,
    }
}


def test_parse_report_full():
    st = parse_report(BASE, FULL, now=100.0)
    assert st.connection is Connection.ONLINE
    assert st.gcode_state is GcodeState.RUNNING
    assert st.percent == 42
    assert st.remaining_min == 75
    assert st.task_name == "benchy.3mf"
    assert st.layer == 120 and st.total_layers == 340
    assert st.last_report_at == 100.0


def test_parse_report_merges_delta():
    prev = parse_report(BASE, FULL, now=100.0)
    st = parse_report(prev, {"print": {"mc_percent": 43}}, now=101.0)
    assert st.gcode_state is GcodeState.RUNNING  # kept from prev
    assert st.percent == 43
    assert st.remaining_min == 75
    assert st.last_report_at == 101.0


def test_parse_report_coerces_percent():
    assert parse_report(BASE, {"print": {"mc_percent": "42"}}, now=0).percent == 42
    assert parse_report(BASE, {"print": {"mc_percent": 250}}, now=0).percent == 100
    assert parse_report(BASE, {"print": {"mc_percent": -5}}, now=0).percent == 0
    assert parse_report(BASE, {"print": {"mc_percent": "junk"}}, now=0).percent == 0


def test_parse_report_unknown_state_and_non_print_payload():
    st = parse_report(BASE, {"print": {"gcode_state": "WEIRD"}}, now=0)
    assert st.gcode_state is GcodeState.UNKNOWN
    st2 = parse_report(BASE, {"info": {"command": "get_version"}}, now=5.0)
    assert st2.connection is Connection.ONLINE and st2.last_report_at == 5.0


def test_parse_report_hms_and_error():
    payload = {"print": {"print_error": 50331904, "hms": [{"attr": 117440512, "code": 131074}]}}
    st = parse_report(BASE, payload, now=0)
    assert st.print_error == 50331904
    assert st.hms_codes == ("0700_0000_0002_0002",)
    assert st.has_error()


def test_hms_code_format():
    assert hms_code({"attr": 0x0300_0100, "code": 0x0002_0001}) == "0300_0100_0002_0001"
    assert hms_code({"attr": "x"}) == ""


def test_filament_out_uses_ams_module_prefix():
    st = replace(BASE, hms_codes=("0700_2000_0002_0001",))
    assert st.filament_out()
    assert not replace(BASE, hms_codes=("0300_0100_0001_0001",)).filament_out()


def test_effective_connection_stale():
    st = replace(BASE, connection=Connection.ONLINE, last_report_at=100.0)
    assert effective_connection(st, now=100.0 + STALE_AFTER - 1) is Connection.ONLINE
    assert effective_connection(st, now=100.0 + STALE_AFTER + 1) is Connection.STALE
    off = replace(st, connection=Connection.OFFLINE)
    assert effective_connection(off, now=161.0) is Connection.OFFLINE


def test_stale_threshold_outlasts_pushall_period():
    # A quiet P1/A1 only reports on change; the periodic pushall is what proves it is
    # alive, so STALE must not trip between two pushalls.
    assert STALE_AFTER >= 2 * PUSHALL_EVERY
    from apps.bambu_progress.bambu import PrinterMonitor
    import inspect
    assert inspect.signature(PrinterMonitor.__init__).parameters["pushall_every"].default == PUSHALL_EVERY
