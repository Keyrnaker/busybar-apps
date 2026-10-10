# bambu-progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A BUSY Bar app that shows print progress for three Bambu Lab printers, selectable with the dial, with sound-and-screen alerts on finish/pause/error.

**Architecture:** One asyncio process. Three `PrinterMonitor` tasks subscribe to each printer's local MQTT and push immutable `PrinterState` snapshots into a queue. A `Ui` state machine consumes the queue, detects transitions with a pure `events.detect`, and pure `render_*` functions turn UI state into busylib `DisplayElements`. A 0.5 s render loop draws to the bar; an input loop feeds dial/button events from the bar's WebSocket into the `Ui`. `--demo` swaps the MQTT monitors for scripted `DemoMonitor`s so everything runs on the emulator without printers.

**Tech Stack:** Python 3.12 (`busybar/.venv`), busylib 2.6 (`AsyncBusyBar`), aiomqtt 2.5, pytest + pytest-asyncio. No Pillow: icons are generated as PNG bytes with `zlib`/`struct`.

**Spec:** `docs/superpowers/specs/2026-09-24-bambu-progress-design.md`

## Global Constraints

- Python 3.12 from `busybar/.venv`. Run everything as `.venv/bin/python …` / `.venv/bin/pytest …` from `~/Workspace/busybar`.
- Package path: `apps/bambu_progress/` (underscore, importable). Run as `.venv/bin/python -m apps.bambu_progress.app`.
- Application name on the bar: `bambu-progress`. Main screen priority `50`, notice priority `80`.
- Display: front only, 72×16. Colours as `#RRGGBBAA`.
- Read-only toward printers. Never publish anything except the `pushall` request.
- Never reconnect after an MQTT "not authorized" failure (printer lockout risk).
- Icons: only uploaded custom PNGs (never `stock_path` images). Sounds: only stock `shared/sounds/calendar_event_starts.snd` (event) and `shared/sounds/calendar_reminder_ends.snd` (reminder).
- Max 2 draws per second.
- Commit after every task with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` as the last line.

## Review Focus

Inputs the spec implies but which are easy to get wrong; each has a pinned test in the owning task.

1. **Delta reports from P1/A1** that omit `gcode_state` entirely must keep the previous state and only change the fields present (Task 2, `test_parse_report_merges_delta`).
2. **`mc_percent` arriving as a string** (`"42"`) or out of range must be clamped to an int 0–100, never crash the monitor (Task 2, `test_parse_report_coerces_percent`).
3. **First report after connect** must not fire FINISH/PAUSE/ERROR notices for a printer that was already finished/paused when the app started (Task 3, `test_no_event_on_first_report`).
4. **Dial input while a notice is showing** must dismiss the notice and not move the selection (Task 6, `test_input_during_notice_dismisses_only`).
5. **Printer count of 1 or 2** must not break list windowing or dial wrap (Task 5, `test_list_window_small_counts`; Task 6, `test_encoder_wraps_with_two_printers`).

---

## File Structure

```
busybar/
├── pytest.ini                         # asyncio_mode=auto, pythonpath=.
├── requirements.txt                   # + aiomqtt, pytest, pytest-asyncio
├── apps/
│   ├── __init__.py
│   └── bambu_progress/
│       ├── __init__.py
│       ├── config.py      # PrinterConfig, AppConfig, load_config, ConfigError, COLORS
│       ├── bambu.py       # PrinterState, Connection, GcodeState, parse_report, hms_code, effective_connection, PrinterMonitor
│       ├── events.py      # Event, EventKind, detect
│       ├── icons.py       # BITMAPS, to_png, icon_filename, required_icons, ensure_uploaded
│       ├── render.py      # colours, layout, format_remaining, list_window, render_list/detail/notice
│       ├── ui.py          # Screen, Notice, Ui, parse_input_events
│       ├── demo.py        # DEMO_CONFIGS, DemoMonitor
│       ├── app.py         # CLI, wiring, render_loop, input_loop
│       ├── printers.example.toml
│       ├── manifest.yaml
│       └── tests/
│           ├── __init__.py
│           ├── test_config.py
│           ├── test_bambu.py
│           ├── test_events.py
│           ├── test_icons.py
│           ├── test_render.py
│           ├── test_ui.py
│           ├── test_monitor.py
│           └── test_demo.py
```

---

### Task 1: Scaffold + config loading

**Files:**
- Create: `pytest.ini`, `apps/__init__.py`, `apps/bambu_progress/__init__.py`, `apps/bambu_progress/tests/__init__.py`
- Create: `apps/bambu_progress/config.py`, `apps/bambu_progress/printers.example.toml`
- Modify: `requirements.txt`
- Test: `apps/bambu_progress/tests/test_config.py`

**Interfaces:**
- Produces:
  - `COLORS: dict[str, str]` — `{"mint": "#63E6BE", "amber": "#FFBF47", "blue": "#5096FF", "rose": "#FF5E93"}`
  - `@dataclass(frozen=True) PrinterConfig(name: str, ip: str, serial: str, access_code: str, color: str)` — `color` is the resolved hex like `"#63E6BE"`.
  - `@dataclass(frozen=True) AppConfig(host: str, token: str | None, printers: list[PrinterConfig])`
  - `class ConfigError(Exception)`
  - `parse_config(data: dict) -> AppConfig` and `load_config(path: Path) -> AppConfig`

- [ ] **Step 1: Create package scaffolding and pytest config**

```bash
cd ~/Workspace/busybar
mkdir -p apps/bambu_progress/tests
touch apps/__init__.py apps/bambu_progress/__init__.py apps/bambu_progress/tests/__init__.py
cat > pytest.ini <<'INI'
[pytest]
asyncio_mode = auto
pythonpath = .
testpaths = apps
INI
cat > requirements.txt <<'REQ'
busylib>=2.6.0
aiomqtt>=2.5.0
pytest>=8
pytest-asyncio>=1.0
REQ
.venv/bin/pip install -q -r requirements.txt
```

- [ ] **Step 2: Write the failing tests**

`apps/bambu_progress/tests/test_config.py`:
```python
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
    data = {"printers": [{"name": "A", "ip": "1.2.3.4", "serial": "S1", "access_code": "1"}]}
    cfg = parse_config(data)
    assert cfg.host == "10.0.4.20"
    assert cfg.printers[0].color == COLORS["mint"]


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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'apps.bambu_progress.config'`

- [ ] **Step 4: Implement config.py**

`apps/bambu_progress/config.py`:
```python
"""printers.toml loading and validation."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_HOST = "10.0.4.20"

COLORS: dict[str, str] = {
    "mint": "#63E6BE",
    "amber": "#FFBF47",
    "blue": "#5096FF",
    "rose": "#FF5E93",
}
_COLOR_ORDER = list(COLORS)


class ConfigError(Exception):
    """Configuration is missing or invalid; message says where."""


@dataclass(frozen=True)
class PrinterConfig:
    name: str
    ip: str
    serial: str
    access_code: str
    color: str  # resolved "#RRGGBB"


@dataclass(frozen=True)
class AppConfig:
    host: str
    token: str | None
    printers: list[PrinterConfig]


_REQUIRED = ("name", "ip", "serial", "access_code")


def _printer(index: int, raw: Any) -> PrinterConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"printers[{index}] must be a table")
    for key in _REQUIRED:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"printers[{index}].{key} missing")
    color_name = raw.get("color", _COLOR_ORDER[index % len(_COLOR_ORDER)])
    if color_name not in COLORS:
        raise ConfigError(
            f"printers[{index}].color must be one of {', '.join(_COLOR_ORDER)}, got {color_name!r}"
        )
    return PrinterConfig(
        name=raw["name"].strip(),
        ip=raw["ip"].strip(),
        serial=raw["serial"].strip(),
        access_code=raw["access_code"].strip(),
        color=COLORS[color_name],
    )


def parse_config(data: dict[str, Any]) -> AppConfig:
    busybar = data.get("busybar") or {}
    host = str(busybar.get("host") or DEFAULT_HOST)
    token_raw = busybar.get("token")
    token = str(token_raw) if token_raw else None

    raw_printers = data.get("printers")
    if not isinstance(raw_printers, list) or not raw_printers:
        raise ConfigError("config needs at least one printer ([[printers]])")
    printers = [_printer(i, raw) for i, raw in enumerate(raw_printers)]

    seen: dict[str, int] = {}
    for i, p in enumerate(printers):
        if p.serial in seen:
            raise ConfigError(f"printers[{i}] has duplicate serial {p.serial!r} (same as printers[{seen[p.serial]}])")
        seen[p.serial] = i
    return AppConfig(host=host, token=token, printers=printers)


def load_config(path: Path) -> AppConfig:
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    return parse_config(data)
```

`apps/bambu_progress/printers.example.toml`:
```toml
# Copy to printers.toml and fill in. Find IP / access code on the printer:
# Settings > Network (IP) and Settings > LAN Mode / Access Code.
[busybar]
host = "10.0.4.20"   # USB default; --host on the command line overrides
token = ""           # Wi-Fi access PIN if you set one on the bar

[[printers]]
name = "P1S-A"
ip = "192.168.0.31"
serial = "01P00A000000000"
access_code = "12345678"
color = "mint"        # mint | amber | blue | rose

[[printers]]
name = "P1S-B"
ip = "192.168.0.32"
serial = "01P00A000000001"
access_code = "12345678"
color = "amber"

[[printers]]
name = "X1C"
ip = "192.168.0.33"
serial = "00M00A000000000"
access_code = "12345678"
color = "blue"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_config.py -q`
Expected: `8 passed`

- [ ] **Step 6: Commit**

```bash
cd ~/Workspace/busybar
printf 'printers.toml\n' >> .gitignore
git add pytest.ini requirements.txt .gitignore apps
git commit -m "feat(bambu-progress): scaffold package and config loading

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: PrinterState and report parsing

**Files:**
- Create: `apps/bambu_progress/bambu.py` (state + parsing only; the monitor is Task 7)
- Test: `apps/bambu_progress/tests/test_bambu.py`

**Interfaces:**
- Produces:
  - `class Connection(Enum)`: `CONNECTING, ONLINE, STALE, OFFLINE, AUTH_ERROR`
  - `class GcodeState(str, Enum)`: `IDLE="IDLE", PREPARE="PREPARE", RUNNING="RUNNING", PAUSE="PAUSE", FINISH="FINISH", FAILED="FAILED", UNKNOWN="UNKNOWN"`
  - `@dataclass(frozen=True) PrinterState(name, connection=CONNECTING, gcode_state=UNKNOWN, percent=0, remaining_min=0, task_name="", print_error=0, hms_codes=(), layer=0, total_layers=0, last_report_at=0.0)` with methods `has_error() -> bool`, `filament_out() -> bool`, `is_printing() -> bool` (RUNNING or PREPARE)
  - `hms_code(entry: dict) -> str` — `"0700_2000_0002_0001"` style from `attr`/`code` ints
  - `parse_report(prev: PrinterState, payload: dict, now: float) -> PrinterState`
  - `effective_connection(state: PrinterState, now: float, stale_after: float = 60.0) -> Connection`
  - `STALE_AFTER = 60.0`, `PUSHALL: dict` (the request JSON)

- [ ] **Step 1: Write the failing tests**

`apps/bambu_progress/tests/test_bambu.py`:
```python
from dataclasses import replace

from apps.bambu_progress.bambu import (
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
    assert effective_connection(st, now=130.0) is Connection.ONLINE
    assert effective_connection(st, now=161.0) is Connection.STALE
    off = replace(st, connection=Connection.OFFLINE)
    assert effective_connection(off, now=161.0) is Connection.OFFLINE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_bambu.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement state and parsing in bambu.py**

`apps/bambu_progress/bambu.py` (the `PrinterMonitor` class is appended in Task 7):
```python
"""Bambu Lab printer state: report parsing now, MQTT monitor in the same file."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

STALE_AFTER = 60.0

PUSHALL: dict[str, Any] = {
    "pushing": {"sequence_id": "0", "command": "pushall", "version": 1, "push_target": 1}
}

# HMS codes are "MMMM_mmmm_cccc_cccc"; the first group is the module. 07 = AMS,
# which is where filament run-out is reported.
_FILAMENT_MODULES = ("0700",)


class Connection(Enum):
    CONNECTING = "connecting"
    ONLINE = "online"
    STALE = "stale"
    OFFLINE = "offline"
    AUTH_ERROR = "auth_error"


class GcodeState(str, Enum):
    IDLE = "IDLE"
    PREPARE = "PREPARE"
    RUNNING = "RUNNING"
    PAUSE = "PAUSE"
    FINISH = "FINISH"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, value: Any) -> "GcodeState":
        try:
            return cls(str(value).upper())
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class PrinterState:
    name: str
    connection: Connection = Connection.CONNECTING
    gcode_state: GcodeState = GcodeState.UNKNOWN
    percent: int = 0
    remaining_min: int = 0
    task_name: str = ""
    print_error: int = 0
    hms_codes: tuple[str, ...] = ()
    layer: int = 0
    total_layers: int = 0
    last_report_at: float = 0.0

    def has_error(self) -> bool:
        return self.gcode_state is GcodeState.FAILED or self.print_error != 0

    def filament_out(self) -> bool:
        return any(code.startswith(_FILAMENT_MODULES) for code in self.hms_codes)

    def is_printing(self) -> bool:
        return self.gcode_state in (GcodeState.RUNNING, GcodeState.PREPARE)


def _int(value: Any, default: int, lo: int | None = None, hi: int | None = None) -> int:
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        return default
    if lo is not None:
        n = max(lo, n)
    if hi is not None:
        n = min(hi, n)
    return n


def hms_code(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    try:
        attr = int(entry.get("attr"))
        code = int(entry.get("code"))
    except (TypeError, ValueError):
        return ""
    return f"{attr >> 16:04X}_{attr & 0xFFFF:04X}_{code >> 16:04X}_{code & 0xFFFF:04X}"


def parse_report(prev: PrinterState, payload: dict[str, Any], now: float) -> PrinterState:
    """Merge one MQTT report into `prev`. Missing fields keep their old value."""
    st = replace(prev, connection=Connection.ONLINE, last_report_at=now)
    p = payload.get("print")
    if not isinstance(p, dict):
        return st
    changes: dict[str, Any] = {}
    if "gcode_state" in p:
        changes["gcode_state"] = GcodeState.parse(p["gcode_state"])
    if "mc_percent" in p:
        changes["percent"] = _int(p["mc_percent"], prev.percent, 0, 100)
    if "mc_remaining_time" in p:
        changes["remaining_min"] = _int(p["mc_remaining_time"], prev.remaining_min, 0)
    if "subtask_name" in p:
        changes["task_name"] = str(p["subtask_name"] or "")
    if "print_error" in p:
        changes["print_error"] = _int(p["print_error"], prev.print_error)
    if "hms" in p:
        raw = p["hms"] if isinstance(p["hms"], list) else []
        changes["hms_codes"] = tuple(c for c in (hms_code(e) for e in raw) if c)
    if "layer_num" in p:
        changes["layer"] = _int(p["layer_num"], prev.layer, 0)
    if "total_layer_num" in p:
        changes["total_layers"] = _int(p["total_layer_num"], prev.total_layers, 0)
    return replace(st, **changes)


def effective_connection(state: PrinterState, now: float, stale_after: float = STALE_AFTER) -> Connection:
    if state.connection is Connection.ONLINE and now - state.last_report_at > stale_after:
        return Connection.STALE
    return state.connection
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_bambu.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/bambu_progress/bambu.py apps/bambu_progress/tests/test_bambu.py
git commit -m "feat(bambu-progress): printer state and MQTT report parsing

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Transition events

**Files:**
- Create: `apps/bambu_progress/events.py`
- Test: `apps/bambu_progress/tests/test_events.py`

**Interfaces:**
- Consumes: `PrinterState`, `Connection`, `GcodeState` from `bambu.py`
- Produces:
  - `class EventKind(Enum)`: `FINISH, PAUSE, ERROR`
  - `@dataclass(frozen=True) Event(printer_index: int, kind: EventKind, message: str)`
  - `detect(index: int, prev: PrinterState, new: PrinterState) -> list[Event]`

- [ ] **Step 1: Write the failing tests**

`apps/bambu_progress/tests/test_events.py`:
```python
from dataclasses import replace

from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState
from apps.bambu_progress.events import Event, EventKind, detect

ON = PrinterState(name="A", connection=Connection.ONLINE, last_report_at=1.0)


def running(**kw):
    return replace(ON, gcode_state=GcodeState.RUNNING, percent=50, **kw)


def test_running_to_finish():
    assert detect(0, running(), replace(running(), gcode_state=GcodeState.FINISH, percent=100)) == [
        Event(0, EventKind.FINISH, "DONE")
    ]


def test_running_to_pause_plain_and_filament():
    assert detect(1, running(), replace(running(), gcode_state=GcodeState.PAUSE)) == [
        Event(1, EventKind.PAUSE, "PAUSED")
    ]
    paused = replace(running(), gcode_state=GcodeState.PAUSE, hms_codes=("0700_2000_0002_0001",))
    assert detect(1, running(), paused) == [Event(1, EventKind.PAUSE, "FILAMENT")]


def test_failed_and_print_error():
    assert detect(2, running(), replace(running(), gcode_state=GcodeState.FAILED)) == [
        Event(2, EventKind.ERROR, "ERROR")
    ]
    errored = replace(running(), print_error=50331904, hms_codes=("0300_0100_0002_0001",))
    assert detect(2, running(), errored) == [Event(2, EventKind.ERROR, "0300_0100_0002_0001")]


def test_error_fires_once_while_error_persists():
    errored = replace(running(), gcode_state=GcodeState.FAILED)
    assert detect(0, errored, replace(errored, percent=51)) == []


def test_no_event_on_first_report():
    fresh = PrinterState(name="A")  # CONNECTING, no report yet
    finished = replace(ON, gcode_state=GcodeState.FINISH, percent=100)
    assert detect(0, fresh, finished) == []
    offline = replace(finished, connection=Connection.OFFLINE)
    assert detect(0, offline, finished) == []  # reconnect must not re-announce


def test_same_state_no_event():
    assert detect(0, running(), running(percent=51)) == []
    assert detect(0, replace(ON, gcode_state=GcodeState.IDLE), replace(ON, gcode_state=GcodeState.IDLE)) == []


def test_idle_to_finish_is_not_announced():
    idle = replace(ON, gcode_state=GcodeState.IDLE)
    assert detect(0, idle, replace(ON, gcode_state=GcodeState.FINISH)) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_events.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement events.py**

```python
"""Pure transition detection between two PrinterState snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .bambu import Connection, GcodeState, PrinterState

_LIVE = (Connection.ONLINE, Connection.STALE)
_ACTIVE = (GcodeState.RUNNING, GcodeState.PREPARE, GcodeState.PAUSE)


class EventKind(Enum):
    FINISH = "finish"
    PAUSE = "pause"
    ERROR = "error"


@dataclass(frozen=True)
class Event:
    printer_index: int
    kind: EventKind
    message: str


def detect(index: int, prev: PrinterState, new: PrinterState) -> list[Event]:
    # Only compare two live snapshots; a first report or a reconnect is not a transition.
    if prev.connection not in _LIVE or new.connection not in _LIVE:
        return []
    events: list[Event] = []
    if not prev.has_error() and new.has_error():
        message = new.hms_codes[0] if new.hms_codes else "ERROR"
        events.append(Event(index, EventKind.ERROR, message))
        return events
    if prev.gcode_state is not new.gcode_state and prev.gcode_state in _ACTIVE:
        if new.gcode_state is GcodeState.FINISH:
            events.append(Event(index, EventKind.FINISH, "DONE"))
        elif new.gcode_state is GcodeState.PAUSE:
            events.append(Event(index, EventKind.PAUSE, "FILAMENT" if new.filament_out() else "PAUSED"))
    return events
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_events.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/bambu_progress/events.py apps/bambu_progress/tests/test_events.py
git commit -m "feat(bambu-progress): detect finish/pause/error transitions

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Pixel-art icons as PNG, upload once

**Files:**
- Create: `apps/bambu_progress/icons.py`
- Test: `apps/bambu_progress/tests/test_icons.py`

**Interfaces:**
- Consumes: `PrinterConfig.color` (Task 1)
- Produces:
  - `APP = "bambu-progress"` (also re-exported by render.py)
  - `BITMAPS: dict[str, tuple[str, ...]]` — keys `printer, nozzle_a, nozzle_b, check, pause, error, hourglass, cross, dot`; each 8 rows × 8 chars, `#` = opaque pixel, `.` = transparent
  - `to_png(bitmap: Sequence[str], rgb_hex: str) -> bytes` — RGBA PNG
  - `icon_filename(name: str, color_hex: str) -> str` — `"check_3ddc84.png"`
  - `required_icons(configs: Sequence[PrinterConfig]) -> dict[str, bytes]` — filename → PNG bytes for every icon/colour the renderer can ask for
  - `async ensure_uploaded(bar, icons: dict[str, bytes], *, application_name: str = APP) -> list[str]` — uploads what is missing or differs in size; returns the uploaded filenames
  - Colour constants used by render too: `WHITE="#FFFFFF"`, `TEXT_GREY="#A8B2C3"`, `DIM="#495365"`, `TRACK="#2A3140"`, `GREEN="#3DDC84"`, `YELLOW="#FFD23F"`, `RED="#FF4D4D"`, `INK="#1A1A1A"` live in `icons.py` under a `Palette` section so render imports them from one place.

- [ ] **Step 1: Write the failing tests**

`apps/bambu_progress/tests/test_icons.py`:
```python
import struct
import zlib

import pytest

from apps.bambu_progress.config import PrinterConfig
from apps.bambu_progress.icons import (
    BITMAPS,
    GREEN,
    WHITE,
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


def test_all_bitmaps_are_8x8():
    for name, rows in BITMAPS.items():
        assert len(rows) == 8, name
        assert all(len(r) == 8 and set(r) <= {"#", "."} for r in rows), name


def test_to_png_encodes_pixels_with_alpha():
    bitmap = ("#.......",) + ("........",) * 7
    w, h, raw = _decode(to_png(bitmap, "#3DDC84"))
    assert (w, h) == (8, 8)
    assert raw[0] == 0  # filter byte
    assert raw[1:5] == bytes([0x3D, 0xDC, 0x84, 0xFF])
    assert raw[5:9] == bytes([0, 0, 0, 0])


def test_icon_filename_is_lowercase_hex():
    assert icon_filename("check", "#3DDC84") == "check_3ddc84.png"


def test_required_icons_cover_every_accent():
    cfgs = [
        PrinterConfig("A", "1", "S1", "c", "#63E6BE"),
        PrinterConfig("B", "2", "S2", "c", "#FFBF47"),
    ]
    icons = required_icons(cfgs)
    for accent in ("63e6be", "ffbf47"):
        for name in ("printer", "nozzle_a", "nozzle_b", "hourglass"):
            assert f"{name}_{accent}.png" in icons
    assert icon_filename("check", GREEN) in icons
    assert icon_filename("check", WHITE) in icons
    assert all(v[:8] == b"\x89PNG\r\n\x1a\n" for v in icons.values())


class FakeBar:
    def __init__(self, listing=None, fail_list=False):
        self.listing = listing or []
        self.fail_list = fail_list
        self.uploaded: list[tuple[str, str, int]] = []
        self.listed: list[str] = []

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_icons.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement icons.py**

```python
"""8x8 pixel-art icons, encoded to PNG without Pillow, uploaded once per bar."""
from __future__ import annotations

import logging
import struct
import zlib
from collections.abc import Sequence
from typing import Any

from .config import PrinterConfig

log = logging.getLogger(__name__)

APP = "bambu-progress"
UPLOADS_ROOT = "/ext/user_assets"

# --- Palette -----------------------------------------------------------------
WHITE = "#FFFFFF"
TEXT_GREY = "#A8B2C3"
DIM = "#495365"
TRACK = "#2A3140"
GREEN = "#3DDC84"
YELLOW = "#FFD23F"
RED = "#FF4D4D"
INK = "#1A1A1A"

# --- Bitmaps (8 rows x 8 cols, '#' opaque, '.' transparent) ------------------
BITMAPS: dict[str, tuple[str, ...]] = {
    "printer": (
        "########",
        "...##...",
        "...##...",
        "....#...",
        "........",
        "########",
        "#......#",
        "########",
    ),
    "nozzle_a": (
        ".######.",
        ".######.",
        "..####..",
        "...##...",
        "....#...",
        "........",
        "########",
        "########",
    ),
    "nozzle_b": (
        ".######.",
        ".######.",
        "..####..",
        "...##...",
        "........",
        "....#...",
        "########",
        "########",
    ),
    "check": (
        "........",
        ".......#",
        "......##",
        ".....##.",
        "#...##..",
        "##.##...",
        ".###....",
        "..#.....",
    ),
    "pause": (
        "........",
        ".##..##.",
        ".##..##.",
        ".##..##.",
        ".##..##.",
        ".##..##.",
        ".##..##.",
        "........",
    ),
    "error": (
        "#......#",
        "##....##",
        ".##..##.",
        "..####..",
        "..####..",
        ".##..##.",
        "##....##",
        "#......#",
    ),
    "hourglass": (
        "########",
        ".#....#.",
        "..#..#..",
        "...##...",
        "...##...",
        "..#..#..",
        ".#....#.",
        "########",
    ),
    "cross": (
        "........",
        ".#....#.",
        "..#..#..",
        "...##...",
        "...##...",
        "..#..#..",
        ".#....#.",
        "........",
    ),
    "dot": (
        "........",
        "........",
        "........",
        "...##...",
        "...##...",
        "........",
        "........",
        "........",
    ),
}


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def _rgb(color_hex: str) -> tuple[int, int, int]:
    h = color_hex.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def to_png(bitmap: Sequence[str], rgb_hex: str) -> bytes:
    r, g, b = _rgb(rgb_hex)
    height = len(bitmap)
    width = len(bitmap[0])
    raw = bytearray()
    for row in bitmap:
        raw.append(0)  # filter type: none
        for ch in row:
            raw += bytes((r, g, b, 0xFF)) if ch == "#" else b"\x00\x00\x00\x00"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b"")


def icon_filename(name: str, color_hex: str) -> str:
    return f"{name}_{color_hex.lstrip('#').lower()}.png"


def required_icons(configs: Sequence[PrinterConfig]) -> dict[str, bytes]:
    wanted: set[tuple[str, str]] = set()
    for cfg in configs:
        for name in ("printer", "nozzle_a", "nozzle_b", "hourglass"):
            wanted.add((name, cfg.color))
    wanted.update({
        ("printer", DIM), ("hourglass", DIM), ("cross", DIM), ("dot", DIM),
        ("check", GREEN), ("pause", YELLOW), ("error", RED),
        ("check", WHITE), ("error", WHITE), ("pause", INK),
    })
    return {icon_filename(n, c): to_png(BITMAPS[n], c) for n, c in sorted(wanted)}


async def ensure_uploaded(bar: Any, icons: dict[str, bytes], *, application_name: str = APP) -> list[str]:
    """Upload icons that are missing or have a different size on the bar."""
    remote_sizes: dict[str, int] = {}
    try:
        listing = await bar.storage_list(f"{UPLOADS_ROOT}/{application_name}")
        for entry in listing.list:
            size = getattr(entry, "size", None)
            if size is not None:
                remote_sizes[entry.name] = size
    except Exception as exc:  # noqa: BLE001 - listing is an optimisation only
        log.debug("asset listing failed, uploading everything: %s", exc)
    uploaded: list[str] = []
    for filename, data in icons.items():
        if remote_sizes.get(filename) == len(data):
            continue
        await bar.assets_upload(application_name, filename, data)
        uploaded.append(filename)
    return uploaded
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_icons.py -q`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/bambu_progress/icons.py apps/bambu_progress/tests/test_icons.py
git commit -m "feat(bambu-progress): pixel icons as PNG with size-checked upload

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Renderer (pure functions → DisplayElements)

**Files:**
- Create: `apps/bambu_progress/render.py`
- Test: `apps/bambu_progress/tests/test_render.py`

**Interfaces:**
- Consumes: `PrinterState`, `GcodeState`, `Connection`, `effective_connection` (Task 2); `Event`, `EventKind` (Task 3); `icon_filename`, palette constants, `APP` (Task 4); `PrinterConfig` (Task 1)
- Produces:
  - `PRIORITY_MAIN = 50`, `PRIORITY_NOTICE = 80`, `WIDTH = 72`, `HEIGHT = 16`
  - `rgba(hex6: str, alpha: int = 0xFF) -> str` → `"#3DDC84FF"`
  - `format_remaining(minutes: int) -> str` → `"1h 12m left"`, `"12m left"`, `"<1m left"`
  - `list_window(selected: int, n: int, rows: int = 2) -> int` → first visible index
  - `progress_width(percent: int) -> int` → 0..72
  - `@dataclass(frozen=True) Visual(icon: str, icon_color: str, label: str, label_color: str, bar_color: str | None, show_track: bool, line2: str)`
  - `visual(state: PrinterState, cfg: PrinterConfig, now: float, frame: int) -> Visual`
  - `render_list(states, configs, selected, now, frame) -> types.DisplayElements`
  - `render_detail(state, cfg, now, frame) -> types.DisplayElements`
  - `render_notice(event: Event, cfg: PrinterConfig) -> types.DisplayElements`

- [ ] **Step 1: Write the failing tests**

`apps/bambu_progress/tests/test_render.py`:
```python
from dataclasses import replace

from busylib import types

from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState
from apps.bambu_progress.config import PrinterConfig
from apps.bambu_progress.events import Event, EventKind
from apps.bambu_progress.icons import DIM, GREEN, RED, TRACK, WHITE, YELLOW
from apps.bambu_progress.render import (
    PRIORITY_MAIN,
    PRIORITY_NOTICE,
    format_remaining,
    list_window,
    progress_width,
    render_detail,
    render_list,
    render_notice,
    rgba,
    visual,
)

CFG = [
    PrinterConfig("P1S-A", "1", "S1", "c", "#63E6BE"),
    PrinterConfig("P1S-B", "2", "S2", "c", "#FFBF47"),
    PrinterConfig("X1C", "3", "S3", "c", "#5096FF"),
]
NOW = 1000.0
ON = PrinterState(name="P1S-A", connection=Connection.ONLINE, last_report_at=NOW)


def running(pct=67, mins=72):
    return replace(ON, gcode_state=GcodeState.RUNNING, percent=pct, remaining_min=mins)


def by_type(elements, kind):
    return [e for e in elements.elements if e.type == kind]


def test_rgba_and_format_remaining():
    assert rgba("#3DDC84") == "#3DDC84FF"
    assert rgba("#3ddc84", 0x60) == "#3DDC8460"
    assert format_remaining(72) == "1h 12m left"
    assert format_remaining(12) == "12m left"
    assert format_remaining(0) == "<1m left"
    assert format_remaining(125) == "2h 5m left"


def test_list_window_small_counts():
    assert [list_window(i, 3) for i in range(3)] == [0, 0, 2]
    assert [list_window(i, 2) for i in range(2)] == [0, 0]
    assert list_window(0, 1) == 0


def test_progress_width():
    assert progress_width(0) == 0
    assert progress_width(50) == 36
    assert progress_width(100) == 72


def test_visual_states():
    v = visual(running(), CFG[0], NOW, frame=0)
    assert (v.icon, v.icon_color, v.label, v.bar_color) == ("nozzle_a", "#63E6BE", "67%", "#63E6BE")
    assert visual(running(), CFG[0], NOW, frame=1).icon == "nozzle_b"
    assert v.line2 == "1h 12m left"

    done = replace(ON, gcode_state=GcodeState.FINISH, percent=100, task_name="benchy.3mf")
    v = visual(done, CFG[0], NOW, 0)
    assert (v.icon, v.icon_color, v.label, v.bar_color, v.line2) == ("check", GREEN, "DONE", GREEN, "benchy.3mf")

    paused = replace(running(), gcode_state=GcodeState.PAUSE)
    v = visual(paused, CFG[0], NOW, 0)
    assert (v.icon, v.icon_color, v.label_color, v.bar_color, v.line2) == ("pause", YELLOW, YELLOW, YELLOW, "PAUSED")

    err = replace(running(), print_error=1, hms_codes=("0300_0100_0002_0001",))
    v = visual(err, CFG[0], NOW, 0)
    assert (v.icon, v.icon_color, v.label, v.line2) == ("error", RED, "ERR", "0300_0100_0002_0001")

    idle = replace(ON, gcode_state=GcodeState.IDLE)
    v = visual(idle, CFG[0], NOW, 0)
    assert (v.icon, v.icon_color, v.label, v.bar_color, v.line2) == ("dot", DIM, "", None, "idle")

    prep = replace(ON, gcode_state=GcodeState.PREPARE)
    v = visual(prep, CFG[0], NOW, 0)
    assert (v.icon, v.label, v.bar_color, v.show_track) == ("hourglass", "PREP", None, True)


def test_visual_connection_states():
    assert visual(PrinterState(name="A"), CFG[0], NOW, 0).line2 == "connecting"
    off = replace(ON, connection=Connection.OFFLINE)
    assert visual(off, CFG[0], NOW, 0).label == "OFF"
    stale = replace(running(), last_report_at=NOW - 200)
    assert visual(stale, CFG[0], NOW, 0).label == "STALE"
    auth = replace(ON, connection=Connection.AUTH_ERROR)
    assert visual(auth, CFG[0], NOW, 0).line2 == "bad access code"


def test_render_list_two_rows_selected_highlighted():
    states = [running(), replace(ON, gcode_state=GcodeState.IDLE, name="P1S-B"), replace(ON, name="X1C")]
    out = render_list(states, CFG, selected=1, now=NOW, frame=0)
    assert out.application_name == "bambu-progress" and out.priority == PRIORITY_MAIN
    images = by_type(out, "image")
    texts = by_type(out, "text")
    # rows 0 and 1 visible (window starts at 0): printer icon per row + status icon per row
    assert [i.y for i in images if i.x == 0] == [0, 8]
    assert images[0].path == "printer_495365.png"  # row 0 not selected -> dim
    assert images[2].path == "printer_ffbf47.png"  # row 1 selected -> accent
    names = [t for t in texts if t.x == 10]
    assert [t.text for t in names] == ["P1S-A", "P1S-B"]
    assert names[0].color == rgba("#A8B2C3") and names[1].color == rgba(WHITE)
    labels = [t for t in texts if t.x == 71]
    assert [t.text for t in labels] == ["67%"]  # idle row has no label


def test_render_list_third_printer_alone_on_second_page():
    states = [running(), running(), replace(running(), name="X1C")]
    out = render_list(states, CFG, selected=2, now=NOW, frame=0)
    assert [i.y for i in by_type(out, "image") if i.x == 0] == [0]
    assert by_type(out, "text")[0].text == "X1C"


def test_render_detail_running_bar():
    out = render_detail(running(50), CFG[0], NOW, frame=0)
    rects = by_type(out, "rectangle")
    assert [(r.x, r.y, r.width, r.height) for r in rects] == [(0, 13, 72, 3), (0, 13, 36, 3)]
    assert rects[0].fill_colors == [rgba(TRACK)] and rects[1].fill_colors == [rgba("#63E6BE")]
    texts = {t.text for t in by_type(out, "text")}
    assert {"P1S-A", "50%", "1h 12m left"} <= texts
    assert by_type(out, "image")[0].path == "nozzle_a_63e6be.png"


def test_render_detail_paused_blinks_and_idle_has_no_bar():
    paused = replace(running(50), gcode_state=GcodeState.PAUSE)
    fill0 = by_type(render_detail(paused, CFG[0], NOW, 0), "rectangle")[1].fill_colors[0]
    fill1 = by_type(render_detail(paused, CFG[0], NOW, 1), "rectangle")[1].fill_colors[0]
    assert {fill0, fill1} == {rgba(YELLOW), rgba(YELLOW, 0x60)}
    idle = replace(ON, gcode_state=GcodeState.IDLE)
    out = render_detail(idle, CFG[0], NOW, 0)
    assert by_type(out, "rectangle") == []
    assert by_type(out, "image")[0].path == "printer_495365.png"


def test_render_detail_zero_percent_has_track_only():
    out = render_detail(running(0), CFG[0], NOW, 0)
    assert len(by_type(out, "rectangle")) == 1


def test_render_detail_finish_scrolls_long_task_name():
    done = replace(ON, gcode_state=GcodeState.FINISH, percent=100, task_name="a_very_long_file_name_here.3mf")
    line2 = [t for t in by_type(render_detail(done, CFG[0], NOW, 0), "text") if t.font == "tiny"][0]
    assert line2.width == 62 and line2.scroll_rate and line2.scroll_rate > 0


def test_render_notice():
    out = render_notice(Event(1, EventKind.PAUSE, "FILAMENT"), CFG[1])
    assert out.priority == PRIORITY_NOTICE
    bg = by_type(out, "rectangle")[0]
    assert (bg.x, bg.y, bg.width, bg.height, bg.fill_colors) == (0, 0, 72, 16, [rgba(YELLOW)])
    assert by_type(out, "image")[0].path == "pause_1a1a1a.png"
    assert [t.text for t in by_type(out, "text")] == ["P1S-B", "FILAMENT"]
    done = render_notice(Event(0, EventKind.FINISH, "DONE"), CFG[0])
    assert by_type(done, "image")[0].path == "check_ffffff.png"
    assert by_type(done, "rectangle")[0].fill_colors == [rgba(GREEN)]
    err = render_notice(Event(0, EventKind.ERROR, "0300_0100_0002_0001"), CFG[0])
    assert by_type(err, "rectangle")[0].fill_colors == [rgba(RED)]
    assert isinstance(err, types.DisplayElements)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_render.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement render.py**

```python
"""Pure rendering: (state, ui) -> busylib DisplayElements. No I/O here."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from busylib import types

from .bambu import Connection, GcodeState, PrinterState, effective_connection
from .config import PrinterConfig
from .events import Event, EventKind
from .icons import APP, DIM, GREEN, INK, RED, TEXT_GREY, TRACK, WHITE, YELLOW, icon_filename

PRIORITY_MAIN = 50
PRIORITY_NOTICE = 80
WIDTH = 72
HEIGHT = 16
ROW_H = 8
ROWS = 2
NAME_X = 10
LINE2_WIDTH = WIDTH - NAME_X
SCROLL_AFTER = 15  # characters; longer line2 texts scroll


def rgba(hex6: str, alpha: int = 0xFF) -> str:
    return f"#{hex6.lstrip('#').upper()}{alpha:02X}"


def format_remaining(minutes: int) -> str:
    if minutes <= 0:
        return "<1m left"
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m left" if h else f"{m}m left"


def list_window(selected: int, n: int, rows: int = ROWS) -> int:
    if n <= rows:
        return 0
    return (selected // rows) * rows


def progress_width(percent: int) -> int:
    return round(WIDTH * max(0, min(100, percent)) / 100)


@dataclass(frozen=True)
class Visual:
    icon: str
    icon_color: str
    label: str
    label_color: str
    bar_color: str | None
    show_track: bool
    line2: str


def visual(state: PrinterState, cfg: PrinterConfig, now: float, frame: int) -> Visual:
    conn = effective_connection(state, now)
    accent = cfg.color
    if conn is Connection.AUTH_ERROR:
        return Visual("cross", DIM, "AUTH", DIM, None, False, "bad access code")
    if conn is Connection.OFFLINE:
        return Visual("cross", DIM, "OFF", DIM, None, False, "offline")
    if conn is Connection.STALE:
        return Visual("cross", DIM, "STALE", DIM, None, False, "no data")
    if conn is Connection.CONNECTING:
        return Visual("hourglass", DIM, "...", DIM, None, False, "connecting")

    pct = f"{state.percent}%"
    if state.has_error():
        return Visual("error", RED, "ERR", RED, RED, True, state.hms_codes[0] if state.hms_codes else "error")
    gs = state.gcode_state
    if gs is GcodeState.FINISH:
        return Visual("check", GREEN, "DONE", GREEN, GREEN, True, state.task_name or "done")
    if gs is GcodeState.PAUSE:
        return Visual("pause", YELLOW, pct, YELLOW, YELLOW, True, "FILAMENT" if state.filament_out() else "PAUSED")
    if gs is GcodeState.RUNNING:
        icon = "nozzle_a" if frame % 2 == 0 else "nozzle_b"
        return Visual(icon, accent, pct, accent, accent, True, format_remaining(state.remaining_min))
    if gs is GcodeState.PREPARE:
        return Visual("hourglass", accent, "PREP", accent, None, True, "preparing")
    return Visual("dot", DIM, "", DIM, None, False, "idle")


def _text(id: str, x: int, y: int, text: str, font: str, color: str, align: str = "mid_left", **extra) -> types.TextElement:
    return types.TextElement(id=id, x=x, y=y, text=text, font=font, color=color, align=align, **extra)


def _rect(id: str, x: int, y: int, w: int, h: int, color: str) -> types.RectangleElement:
    return types.RectangleElement(id=id, x=x, y=y, width=w, height=h, fill="solid", fill_colors=[color], border_width=0)


def render_list(
    states: Sequence[PrinterState], configs: Sequence[PrinterConfig], selected: int, now: float, frame: int
) -> types.DisplayElements:
    start = list_window(selected, len(states))
    elements: list = []
    for row, i in enumerate(range(start, min(start + ROWS, len(states)))):
        state, cfg = states[i], configs[i]
        sel = i == selected
        y = row * ROW_H
        v = visual(state, cfg, now, frame)
        elements.append(types.ImageElement(id=f"{row}0", x=0, y=y, path=icon_filename("printer", cfg.color if sel else DIM)))
        elements.append(_text(f"{row}1", NAME_X, y + 4, cfg.name[:8], "small", rgba(WHITE if sel else TEXT_GREY)))
        elements.append(types.ImageElement(id=f"{row}2", x=46, y=y, path=icon_filename(v.icon, v.icon_color)))
        if v.label:
            elements.append(_text(f"{row}3", WIDTH - 1, y + 4, v.label, "small", rgba(v.label_color), align="mid_right"))
    return types.DisplayElements(application_name=APP, priority=PRIORITY_MAIN, elements=elements)


def render_detail(state: PrinterState, cfg: PrinterConfig, now: float, frame: int) -> types.DisplayElements:
    v = visual(state, cfg, now, frame)
    main_icon = ("printer", DIM) if v.icon == "dot" else (v.icon, v.icon_color)
    elements: list = [
        types.ImageElement(id="1", x=0, y=0, path=icon_filename(*main_icon)),
        _text("2", NAME_X, 3, cfg.name, "small", rgba(WHITE)),
    ]
    if v.label:
        elements.append(_text("3", WIDTH - 1, 3, v.label, "bold", rgba(v.label_color), align="mid_right"))
    line2_extra = {"width": LINE2_WIDTH, "scroll_rate": 20} if len(v.line2) > SCROLL_AFTER else {}
    elements.append(_text("4", NAME_X, 10, v.line2, "tiny", rgba(TEXT_GREY), **line2_extra))
    if v.show_track:
        elements.append(_rect("5", 0, 13, WIDTH, 3, rgba(TRACK)))
        w = progress_width(state.percent)
        if v.bar_color and w > 0:
            alpha = 0x60 if state.gcode_state is GcodeState.PAUSE and frame % 2 else 0xFF
            elements.append(_rect("6", 0, 13, w, 3, rgba(v.bar_color, alpha)))
    return types.DisplayElements(application_name=APP, priority=PRIORITY_MAIN, elements=elements)


_NOTICE_STYLE = {
    EventKind.FINISH: (GREEN, "check", WHITE),
    EventKind.PAUSE: (YELLOW, "pause", INK),
    EventKind.ERROR: (RED, "error", WHITE),
}


def render_notice(event: Event, cfg: PrinterConfig) -> types.DisplayElements:
    bg, icon, fg = _NOTICE_STYLE[event.kind]
    elements = [
        _rect("0", 0, 0, WIDTH, HEIGHT, rgba(bg)),
        types.ImageElement(id="1", x=2, y=4, path=icon_filename(icon, fg)),
        _text("2", 13, 4, cfg.name, "bold", rgba(fg)),
        _text("3", 13, 12, event.message, "tiny", rgba(fg)),
    ]
    return types.DisplayElements(
        application_name=APP, priority=PRIORITY_NOTICE, led_notification_color=rgba(bg), elements=elements
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_render.py -q`
Expected: `13 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/bambu_progress/render.py apps/bambu_progress/tests/test_render.py
git commit -m "feat(bambu-progress): list, detail and notice renderers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Ui state machine and input parsing

**Files:**
- Create: `apps/bambu_progress/ui.py`
- Test: `apps/bambu_progress/tests/test_ui.py`

**Interfaces:**
- Consumes: `PrinterState`, `PrinterConfig`, `detect`, `Event`, `EventKind`, `render_list/detail/notice`
- Produces:
  - `class Screen(Enum)`: `LIST, DETAIL, HIDDEN`
  - `NOTICE_SECONDS = 8.0`
  - `SOUNDS: dict[EventKind, str]` — FINISH/ERROR → `"shared/sounds/calendar_event_starts.snd"`, PAUSE → `"shared/sounds/calendar_reminder_ends.snd"`
  - `@dataclass Notice(event: Event, until: float | None)` — `None` means "until a button is pressed"
  - `class Ui`:
    - `__init__(self, configs: Sequence[PrinterConfig])`
    - attributes: `states: list[PrinterState]`, `screen: Screen`, `selected: int`, `queue: deque[Event]`, `active: Notice | None`, `frame: int`
    - `apply_update(self, index: int, state: PrinterState) -> list[Event]`
    - `handle_input(self, kind: str, value) -> None` — `kind` is `"encoder"` (value: int delta) or `"button"` (value: `"ok" | "back" | "start" | ...`)
    - `tick(self, now: float) -> None`
    - `pop_sound(self) -> str | None`
    - `render(self, now: float) -> types.DisplayElements | None` — `None` means the screen should be cleared
  - `parse_input_events(message: dict) -> list[tuple[str, Any]]`

- [ ] **Step 1: Write the failing tests**

`apps/bambu_progress/tests/test_ui.py`:
```python
from dataclasses import replace

from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState
from apps.bambu_progress.config import PrinterConfig
from apps.bambu_progress.events import EventKind
from apps.bambu_progress.render import PRIORITY_MAIN, PRIORITY_NOTICE
from apps.bambu_progress.ui import NOTICE_SECONDS, SOUNDS, Screen, Ui, parse_input_events

CFG = [
    PrinterConfig("A", "1", "S1", "c", "#63E6BE"),
    PrinterConfig("B", "2", "S2", "c", "#FFBF47"),
    PrinterConfig("C", "3", "S3", "c", "#5096FF"),
]


def on(name, gs=GcodeState.RUNNING, **kw):
    return PrinterState(name=name, connection=Connection.ONLINE, gcode_state=gs, last_report_at=1.0, **kw)


def test_initial_state_and_navigation():
    ui = Ui(CFG)
    assert ui.screen is Screen.LIST and ui.selected == 0
    ui.handle_input("encoder", 1)
    ui.handle_input("encoder", 1)
    ui.handle_input("encoder", 1)
    assert ui.selected == 0  # wrapped
    ui.handle_input("encoder", -1)
    assert ui.selected == 2
    ui.handle_input("button", "ok")
    assert ui.screen is Screen.DETAIL
    ui.handle_input("encoder", 1)
    assert ui.screen is Screen.DETAIL and ui.selected == 0
    ui.handle_input("button", "back")
    assert ui.screen is Screen.LIST
    ui.handle_input("button", "back")
    assert ui.screen is Screen.HIDDEN
    assert ui.render(now=0.0) is None
    ui.handle_input("button", "start")
    assert ui.screen is Screen.LIST


def test_encoder_wraps_with_two_printers():
    ui = Ui(CFG[:2])
    ui.handle_input("encoder", -1)
    assert ui.selected == 1
    ui.handle_input("encoder", 3)
    assert ui.selected == 0


def test_render_priority_follows_screen():
    ui = Ui(CFG)
    assert ui.render(0.0).priority == PRIORITY_MAIN
    ui.handle_input("button", "ok")
    assert ui.render(0.0).priority == PRIORITY_MAIN


def test_update_detects_event_and_shows_notice_with_sound():
    ui = Ui(CFG)
    ui.apply_update(1, on("B"))
    events = ui.apply_update(1, on("B", GcodeState.FINISH, percent=100))
    assert [e.kind for e in events] == [EventKind.FINISH]
    assert ui.active is None and len(ui.queue) == 1
    ui.tick(now=10.0)
    assert ui.active is not None and ui.active.until == 10.0 + NOTICE_SECONDS
    assert ui.pop_sound() == SOUNDS[EventKind.FINISH]
    assert ui.pop_sound() is None
    assert ui.render(10.0).priority == PRIORITY_NOTICE
    ui.tick(now=10.0 + NOTICE_SECONDS + 0.1)
    assert ui.active is None
    assert ui.render(20.0).priority == PRIORITY_MAIN


def test_error_notice_stays_until_button():
    ui = Ui(CFG)
    ui.apply_update(0, on("A"))
    ui.apply_update(0, on("A", GcodeState.FAILED))
    ui.tick(1.0)
    assert ui.active.until is None
    ui.tick(10_000.0)
    assert ui.active is not None
    ui.handle_input("button", "ok")
    assert ui.active is None
    assert ui.screen is Screen.LIST  # the press only dismissed


def test_input_during_notice_dismisses_only():
    ui = Ui(CFG)
    ui.apply_update(2, on("C"))
    ui.apply_update(2, on("C", GcodeState.PAUSE))
    ui.tick(1.0)
    ui.handle_input("encoder", 1)
    assert ui.active is None and ui.selected == 0


def test_notice_queue_dedupes_and_orders():
    ui = Ui(CFG)
    ui.apply_update(0, on("A"))
    ui.apply_update(1, on("B"))
    ui.apply_update(0, on("A", GcodeState.PAUSE))
    ui.apply_update(0, on("A", GcodeState.RUNNING))
    ui.apply_update(0, on("A", GcodeState.PAUSE))  # duplicate while first still queued
    ui.apply_update(1, on("B", GcodeState.FINISH))
    assert [(e.printer_index, e.kind) for e in ui.queue] == [(0, EventKind.PAUSE), (1, EventKind.FINISH)]
    ui.tick(1.0)
    assert ui.active.event.printer_index == 0
    ui.tick(1.0 + NOTICE_SECONDS + 1)
    assert ui.active.event.printer_index == 1


def test_hidden_screen_restored_after_notice():
    ui = Ui(CFG)
    ui.handle_input("button", "back")
    assert ui.screen is Screen.HIDDEN
    ui.apply_update(0, on("A"))
    ui.apply_update(0, on("A", GcodeState.FINISH))
    ui.tick(1.0)
    assert ui.render(1.0) is not None
    ui.tick(1.0 + NOTICE_SECONDS + 1)
    assert ui.render(20.0) is None


def test_tick_advances_frame():
    ui = Ui(CFG)
    ui.tick(0.0)
    ui.tick(0.5)
    assert ui.frame == 2


def test_parse_input_events():
    msg = {
        "updates": [
            {"input": {"button_event": {"button": "ok", "action": "press"}}},
            {"input": {"button_event": {"button": "back", "action": "release"}}},
            {"input": {"encoder_event": {"delta": -2}}},
            {"input": {"encoder_event": {"delta": 0}}},
            {"display": {"brightness": 50}},
        ]
    }
    assert parse_input_events(msg) == [("button", "ok"), ("encoder", -2)]
    assert parse_input_events({"nope": 1}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_ui.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement ui.py**

```python
"""Screen state machine: list / detail / hidden plus a notice overlay queue."""
from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from busylib import types

from .bambu import PrinterState
from .config import PrinterConfig
from .events import Event, EventKind, detect
from .render import render_detail, render_list, render_notice

NOTICE_SECONDS = 8.0

SOUNDS: dict[EventKind, str] = {
    EventKind.FINISH: "shared/sounds/calendar_event_starts.snd",
    EventKind.PAUSE: "shared/sounds/calendar_reminder_ends.snd",
    EventKind.ERROR: "shared/sounds/calendar_event_starts.snd",
}


class Screen(Enum):
    LIST = "list"
    DETAIL = "detail"
    HIDDEN = "hidden"


@dataclass
class Notice:
    event: Event
    until: float | None  # None: stays until a button press


class Ui:
    def __init__(self, configs: Sequence[PrinterConfig]) -> None:
        self.configs = list(configs)
        self.states: list[PrinterState] = [PrinterState(name=c.name) for c in self.configs]
        self.screen = Screen.LIST
        self.selected = 0
        self.queue: deque[Event] = deque()
        self.active: Notice | None = None
        self.frame = 0
        self._sound: str | None = None

    # -- updates from monitors -------------------------------------------------
    def apply_update(self, index: int, state: PrinterState) -> list[Event]:
        prev = self.states[index]
        self.states[index] = state
        events = detect(index, prev, state)
        for event in events:
            if self._is_pending(event):
                continue
            self.queue.append(event)
        return events

    def _is_pending(self, event: Event) -> bool:
        same = lambda e: e.printer_index == event.printer_index and e.kind == event.kind  # noqa: E731
        if self.active is not None and same(self.active.event):
            return True
        return any(same(e) for e in self.queue)

    # -- input from the bar ----------------------------------------------------
    def handle_input(self, kind: str, value: Any) -> None:
        if self.active is not None:
            self.active = None  # any input just dismisses the notice
            return
        n = len(self.states)
        if kind == "encoder":
            if self.screen is Screen.HIDDEN:
                self.screen = Screen.LIST
                return
            self.selected = (self.selected + int(value)) % n
            return
        button = str(value)
        if self.screen is Screen.HIDDEN:
            self.screen = Screen.LIST
        elif self.screen is Screen.LIST:
            if button == "ok":
                self.screen = Screen.DETAIL
            elif button == "back":
                self.screen = Screen.HIDDEN
        elif self.screen is Screen.DETAIL:
            if button == "back":
                self.screen = Screen.LIST

    # -- time ------------------------------------------------------------------
    def tick(self, now: float) -> None:
        self.frame += 1
        if self.active is not None and self.active.until is not None and now >= self.active.until:
            self.active = None
        if self.active is None and self.queue:
            event = self.queue.popleft()
            until = None if event.kind is EventKind.ERROR else now + NOTICE_SECONDS
            self.active = Notice(event, until)
            self._sound = SOUNDS[event.kind]

    def pop_sound(self) -> str | None:
        sound, self._sound = self._sound, None
        return sound

    # -- output ----------------------------------------------------------------
    def render(self, now: float) -> types.DisplayElements | None:
        if self.active is not None:
            return render_notice(self.active.event, self.configs[self.active.event.printer_index])
        if self.screen is Screen.HIDDEN:
            return None
        if self.screen is Screen.DETAIL:
            return render_detail(self.states[self.selected], self.configs[self.selected], now, self.frame)
        return render_list(self.states, self.configs, self.selected, now, self.frame)


def parse_input_events(message: dict[str, Any]) -> list[tuple[str, Any]]:
    """Same shape the community home-assistant app reads from stream_status_ws."""
    events: list[tuple[str, Any]] = []
    for update in message.get("updates", []) if isinstance(message, dict) else []:
        inp = update.get("input") if isinstance(update, dict) else None
        if not isinstance(inp, dict):
            continue
        button = inp.get("button_event")
        if isinstance(button, dict) and str(button.get("action", "")).lower() in ("", "press"):
            events.append(("button", str(button.get("button") or "ok").lower()))
        encoder = inp.get("encoder_event")
        if isinstance(encoder, dict):
            try:
                delta = int(encoder.get("delta", 0))
            except (TypeError, ValueError):
                delta = 0
            if delta:
                events.append(("encoder", delta))
    return events
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_ui.py -q`
Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/bambu_progress/ui.py apps/bambu_progress/tests/test_ui.py
git commit -m "feat(bambu-progress): ui state machine with notice queue and input parsing

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: PrinterMonitor (MQTT subscription with reconnect)

**Files:**
- Modify: `apps/bambu_progress/bambu.py` (append the monitor at the end of the file)
- Test: `apps/bambu_progress/tests/test_monitor.py`

**Interfaces:**
- Consumes: `PrinterConfig`, `PrinterState`, `Connection`, `parse_report`, `PUSHALL`
- Produces:
  - `class AuthError(Exception)`
  - `is_auth_error(exc: BaseException) -> bool`
  - `default_client_factory(cfg: PrinterConfig) -> aiomqtt.Client`
  - `class PrinterMonitor`:
    - `__init__(self, index: int, cfg: PrinterConfig, queue: asyncio.Queue, *, client_factory=default_client_factory, sleep=asyncio.sleep, clock=time.monotonic, pushall_every: float = 300.0, backoff_min: float = 2.0, backoff_max: float = 60.0)`
    - `state: PrinterState` (latest emitted)
    - `async run(self) -> None` — loops forever; returns only on auth failure
  - Queue items are `tuple[int, PrinterState]`.
  - A client from `client_factory` must support `async with`, `await subscribe(topic)`, `await publish(topic, payload=...)`, and `async for m in client.messages` where `m.payload` is bytes.

- [ ] **Step 1: Write the failing tests**

`apps/bambu_progress/tests/test_monitor.py`:
```python
import asyncio
import json
from types import SimpleNamespace

import aiomqtt
import pytest

from apps.bambu_progress.bambu import PUSHALL, Connection, GcodeState, PrinterMonitor, is_auth_error
from apps.bambu_progress.config import PrinterConfig

CFG = PrinterConfig("P1S-A", "192.168.0.31", "01P00A123456789", "12345678", "#63E6BE")


class Stop(Exception):
    """Raised by the sleep stub to end run() in tests."""


class FakeClient:
    def __init__(self, payloads, *, enter_error=None):
        self.payloads = payloads
        self.enter_error = enter_error
        self.subscribed: list[str] = []
        self.published: list[tuple[str, str]] = []

    async def __aenter__(self):
        if self.enter_error:
            raise self.enter_error
        return self

    async def __aexit__(self, *exc):
        return False

    async def subscribe(self, topic):
        self.subscribed.append(topic)

    async def publish(self, topic, payload=None, **kw):
        self.published.append((topic, payload))

    @property
    def messages(self):
        return self._gen()

    async def _gen(self):
        for p in self.payloads:
            yield SimpleNamespace(payload=p)
        raise aiomqtt.MqttError("connection lost")


def make_sleep(record, stop_after):
    async def sleep(seconds):
        record.append(seconds)
        if len(record) >= stop_after:
            raise Stop
    return sleep


def drain(queue):
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


async def test_reports_flow_to_queue_and_pushall_sent():
    queue: asyncio.Queue = asyncio.Queue()
    client = FakeClient([json.dumps({"print": {"gcode_state": "RUNNING", "mc_percent": 42}}).encode(), b"not json"])
    sleeps: list[float] = []
    mon = PrinterMonitor(0, CFG, queue, client_factory=lambda cfg: client, sleep=make_sleep(sleeps, 1), clock=lambda: 50.0)
    with pytest.raises(Stop):
        await mon.run()
    assert client.subscribed == ["device/01P00A123456789/report"]
    assert client.published[0] == ("device/01P00A123456789/request", json.dumps(PUSHALL))
    items = drain(queue)
    conns = [s.connection for _, s in items]
    assert conns == [Connection.CONNECTING, Connection.ONLINE, Connection.OFFLINE]
    online = items[1][1]
    assert online.gcode_state is GcodeState.RUNNING and online.percent == 42 and online.last_report_at == 50.0
    assert items[2][1].percent == 42  # OFFLINE keeps the last known fields
    assert sleeps == [2.0]


async def test_auth_failure_stops_without_retry():
    queue: asyncio.Queue = asyncio.Queue()
    client = FakeClient([], enter_error=aiomqtt.MqttError("[code:135] Not authorized"))
    sleeps: list[float] = []
    mon = PrinterMonitor(1, CFG, queue, client_factory=lambda cfg: client, sleep=make_sleep(sleeps, 1))
    await mon.run()  # returns instead of looping
    assert [s.connection for _, s in drain(queue)][-1] is Connection.AUTH_ERROR
    assert sleeps == []


async def test_backoff_doubles_and_caps():
    queue: asyncio.Queue = asyncio.Queue()
    sleeps: list[float] = []
    mon = PrinterMonitor(
        2, CFG, queue,
        client_factory=lambda cfg: FakeClient([], enter_error=aiomqtt.MqttError("refused")),
        sleep=make_sleep(sleeps, 4), backoff_min=2.0, backoff_max=6.0,
    )
    with pytest.raises(Stop):
        await mon.run()
    assert sleeps == [2.0, 4.0, 6.0, 6.0]
    assert all(s.connection in (Connection.CONNECTING, Connection.OFFLINE) for _, s in drain(queue))


async def test_backoff_resets_after_a_message():
    queue: asyncio.Queue = asyncio.Queue()
    sleeps: list[float] = []
    attempts = iter([
        FakeClient([], enter_error=aiomqtt.MqttError("refused")),
        FakeClient([json.dumps({"print": {"mc_percent": 1}}).encode()]),
        FakeClient([], enter_error=aiomqtt.MqttError("refused")),
    ])
    mon = PrinterMonitor(0, CFG, queue, client_factory=lambda cfg: next(attempts), sleep=make_sleep(sleeps, 3))
    with pytest.raises(Stop):
        await mon.run()
    assert sleeps == [2.0, 2.0, 4.0]


def test_is_auth_error_variants():
    assert is_auth_error(aiomqtt.MqttError("Connection Refused: not authorised."))
    assert is_auth_error(aiomqtt.MqttError("[code:135] Not authorized"))
    assert not is_auth_error(aiomqtt.MqttError("timed out"))
    assert is_auth_error(aiomqtt.MqttCodeError(5, "connect"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_monitor.py -q`
Expected: FAIL with `ImportError: cannot import name 'PrinterMonitor'`

- [ ] **Step 3: Append the monitor to bambu.py**

Add these imports at the top of `apps/bambu_progress/bambu.py` (keep the existing ones):
```python
import asyncio
import contextlib
import json
import logging
import ssl
import time
from collections.abc import Awaitable, Callable

import aiomqtt

from .config import PrinterConfig

log = logging.getLogger(__name__)
```

Append at the end of `apps/bambu_progress/bambu.py`:
```python
# --- MQTT monitor --------------------------------------------------------------

MQTT_PORT = 8883
MQTT_USER = "bblp"


class AuthError(Exception):
    """The printer rejected the access code. Do not retry."""


def is_auth_error(exc: BaseException) -> bool:
    rc = getattr(exc, "rc", None)
    rc_value = getattr(rc, "value", rc)
    if rc_value in (5, 135):  # CONNACK 3.1.1 "not authorized" / MQTT 5 reason code
        return True
    return "not authori" in str(exc).lower()


def default_client_factory(cfg: PrinterConfig) -> aiomqtt.Client:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # printers use a self-signed certificate
    return aiomqtt.Client(
        hostname=cfg.ip,
        port=MQTT_PORT,
        username=MQTT_USER,
        password=cfg.access_code,
        tls_context=ctx,
        protocol=aiomqtt.ProtocolVersion.V311,
        identifier=f"busybar-{cfg.serial[-6:]}",
        timeout=10,
        keepalive=30,
    )


class PrinterMonitor:
    def __init__(
        self,
        index: int,
        cfg: PrinterConfig,
        queue: "asyncio.Queue[tuple[int, PrinterState]]",
        *,
        client_factory: Callable[[PrinterConfig], Any] = default_client_factory,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        pushall_every: float = 300.0,
        backoff_min: float = 2.0,
        backoff_max: float = 60.0,
    ) -> None:
        self.index = index
        self.cfg = cfg
        self.queue = queue
        self.client_factory = client_factory
        self.sleep = sleep
        self.clock = clock
        self.pushall_every = pushall_every
        self.backoff_min = backoff_min
        self.backoff_max = backoff_max
        self.state = PrinterState(name=cfg.name)
        self._backoff = backoff_min
        self._report_topic = f"device/{cfg.serial}/report"
        self._request_topic = f"device/{cfg.serial}/request"

    def _emit(self, state: PrinterState) -> None:
        self.state = state
        self.queue.put_nowait((self.index, state))

    async def run(self) -> None:
        while True:
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - every failure becomes OFFLINE + retry
                if is_auth_error(exc):
                    log.error("%s: access code rejected, giving up: %s", self.cfg.name, exc)
                    self._emit(replace(self.state, connection=Connection.AUTH_ERROR))
                    return
                log.warning("%s: connection lost (%s); retry in %.0fs", self.cfg.name, exc, self._backoff)
                self._emit(replace(self.state, connection=Connection.OFFLINE))
                await self.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, self.backoff_max)

    async def _session(self) -> None:
        self._emit(replace(self.state, connection=Connection.CONNECTING))
        async with self.client_factory(self.cfg) as client:
            await client.subscribe(self._report_topic)
            await client.publish(self._request_topic, payload=json.dumps(PUSHALL))
            pusher = asyncio.create_task(self._pushall_loop(client))
            try:
                async for message in client.messages:
                    data = self._decode(message.payload)
                    if data is None:
                        continue
                    self._backoff = self.backoff_min
                    self._emit(parse_report(self.state, data, self.clock()))
            finally:
                pusher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pusher

    async def _pushall_loop(self, client: Any) -> None:
        while True:
            await asyncio.sleep(self.pushall_every)
            await client.publish(self._request_topic, payload=json.dumps(PUSHALL))

    @staticmethod
    def _decode(payload: Any) -> dict[str, Any] | None:
        try:
            data = json.loads(payload if isinstance(payload, (bytes, str)) else bytes(payload))
        except (ValueError, TypeError):
            log.debug("ignoring non-JSON report")
            return None
        return data if isinstance(data, dict) else None
```

Note `_pushall_loop` uses the real `asyncio.sleep` on purpose (it must not consume the test's stub); the tests never wait 300 s because the loop is cancelled when the session ends.

- [ ] **Step 4: Run all tests to verify they pass**

Run: `.venv/bin/pytest -q`
Expected: all pass (`test_monitor.py`: `5 passed`; earlier files unchanged)

- [ ] **Step 5: Commit**

```bash
git add apps/bambu_progress/bambu.py apps/bambu_progress/tests/test_monitor.py
git commit -m "feat(bambu-progress): MQTT printer monitor with backoff and auth stop

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Demo monitors (scripted printers)

**Files:**
- Create: `apps/bambu_progress/demo.py`
- Test: `apps/bambu_progress/tests/test_demo.py`

**Interfaces:**
- Consumes: `PrinterConfig`, `COLORS`, `PrinterState`, `Connection`, `GcodeState`, `detect`
- Produces:
  - `DEMO_CONFIGS: list[PrinterConfig]` (3 printers, ip `"demo"`, serials `DEMO1..3`)
  - `Step = tuple[float, dict[str, Any]]` and `SCENARIOS: list[list[Step]]` (one per demo printer)
  - `class DemoMonitor` with `__init__(self, index, cfg, queue, *, steps=None, sleep=asyncio.sleep, clock=time.monotonic, loop=True)` and `async run(self) -> None` — same queue contract as `PrinterMonitor`

- [ ] **Step 1: Write the failing tests**

`apps/bambu_progress/tests/test_demo.py`:
```python
import asyncio

from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState
from apps.bambu_progress.demo import DEMO_CONFIGS, SCENARIOS, DemoMonitor
from apps.bambu_progress.events import EventKind, detect


async def _collect(index):
    queue: asyncio.Queue = asyncio.Queue()
    holds: list[float] = []

    async def sleep(s):
        holds.append(s)

    await DemoMonitor(index, DEMO_CONFIGS[index], queue, sleep=sleep, clock=lambda: 7.0, loop=False).run()
    states = []
    while not queue.empty():
        states.append(queue.get_nowait()[1])
    return states, holds


def test_three_demo_printers_with_distinct_colors():
    assert len(DEMO_CONFIGS) == 3 == len(SCENARIOS)
    assert len({c.color for c in DEMO_CONFIGS}) == 3


async def test_scenario_0_runs_to_finish_then_idle():
    states, holds = await _collect(0)
    assert states[0].connection is Connection.ONLINE and states[0].gcode_state is GcodeState.RUNNING
    assert states[0].last_report_at == 7.0
    assert any(s.gcode_state is GcodeState.FINISH and s.percent == 100 for s in states)
    assert states[-1].gcode_state is GcodeState.IDLE
    assert len(holds) == len(states) and sum(holds) < 60


async def test_scenario_1_pauses_for_filament_then_finishes():
    states, _ = await _collect(1)
    kinds = []
    prev = PrinterState(name="x")
    for s in states:
        kinds += [(e.kind, e.message) for e in detect(1, prev, s)]
        prev = s
    assert kinds == [(EventKind.PAUSE, "FILAMENT"), (EventKind.FINISH, "DONE")]


async def test_scenario_2_fails_with_error_code():
    states, _ = await _collect(2)
    failed = [s for s in states if s.gcode_state is GcodeState.FAILED]
    assert failed and failed[0].print_error != 0 and failed[0].hms_codes
    assert states[-1].print_error == 0 and states[-1].gcode_state is GcodeState.IDLE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_demo.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement demo.py**

```python
"""Scripted fake printers so the whole UI can be seen on the emulator."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import Any

from .bambu import Connection, GcodeState, PrinterState
from .config import COLORS, PrinterConfig

Step = tuple[float, dict[str, Any]]

DEMO_CONFIGS: list[PrinterConfig] = [
    PrinterConfig("P1S-A", "demo", "DEMO1", "", COLORS["mint"]),
    PrinterConfig("P1S-B", "demo", "DEMO2", "", COLORS["amber"]),
    PrinterConfig("X1C", "demo", "DEMO3", "", COLORS["blue"]),
]


def _ramp(start: int, end: int, step: int, task: str, hold: float = 1.0) -> list[Step]:
    return [
        (hold, {"gcode_state": GcodeState.RUNNING, "percent": p, "remaining_min": (100 - p) * 2, "task_name": task})
        for p in range(start, end + 1, step)
    ]


SCENARIOS: list[list[Step]] = [
    _ramp(0, 100, 5, "benchy.3mf")
    + [(10.0, {"gcode_state": GcodeState.FINISH, "percent": 100, "remaining_min": 0}),
       (5.0, {"gcode_state": GcodeState.IDLE, "percent": 0})],
    _ramp(0, 40, 4, "phone_stand.3mf")
    + [(8.0, {"gcode_state": GcodeState.PAUSE, "hms_codes": ("0700_2000_0002_0001",)}),
       (1.0, {"gcode_state": GcodeState.RUNNING, "hms_codes": ()})]
    + _ramp(44, 100, 4, "phone_stand.3mf")
    + [(6.0, {"gcode_state": GcodeState.FINISH, "remaining_min": 0}),
       (4.0, {"gcode_state": GcodeState.IDLE, "percent": 0})],
    _ramp(0, 25, 5, "gear_set_v3_final.3mf")
    + [(15.0, {"gcode_state": GcodeState.FAILED, "print_error": 50331904, "hms_codes": ("0300_0100_0002_0001",)}),
       (5.0, {"gcode_state": GcodeState.IDLE, "print_error": 0, "hms_codes": (), "percent": 0})],
]


class DemoMonitor:
    def __init__(
        self,
        index: int,
        cfg: PrinterConfig,
        queue: "asyncio.Queue[tuple[int, PrinterState]]",
        *,
        steps: Sequence[Step] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        loop: bool = True,
    ) -> None:
        self.index = index
        self.cfg = cfg
        self.queue = queue
        self.steps = list(steps if steps is not None else SCENARIOS[index % len(SCENARIOS)])
        self.sleep = sleep
        self.clock = clock
        self.loop = loop
        self.state = PrinterState(name=cfg.name)

    async def run(self) -> None:
        while True:
            for hold, changes in self.steps:
                self.state = replace(self.state, connection=Connection.ONLINE, last_report_at=self.clock(), **changes)
                self.queue.put_nowait((self.index, self.state))
                await self.sleep(hold)
            if not self.loop:
                return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_demo.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add apps/bambu_progress/demo.py apps/bambu_progress/tests/test_demo.py
git commit -m "feat(bambu-progress): scripted demo printers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: app.py wiring, manifest, README

**Files:**
- Create: `apps/bambu_progress/app.py`, `apps/bambu_progress/manifest.yaml`
- Modify: `README.md` (project root; add a "bambu-progress" section)
- Test: `apps/bambu_progress/tests/test_app.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `parse_args(argv: list[str] | None = None) -> argparse.Namespace` with `host, token, config, demo, once, verbose`
  - `async render_loop(bar, ui, queue, *, once: bool = False) -> None`
  - `async input_loop(bar, ui) -> None`
  - `async main_async(args) -> None`, `main() -> None`
  - `TICK = 0.5`, `RECONNECT = 5.0`, `DEMO_HOST = "127.0.0.1:8080"`

- [ ] **Step 1: Write the failing tests**

`apps/bambu_progress/tests/test_app.py`:
```python
import asyncio
from pathlib import Path

from busylib import exceptions

from apps.bambu_progress.app import DEMO_HOST, input_loop, parse_args, render_loop
from apps.bambu_progress.bambu import Connection, GcodeState, PrinterState
from apps.bambu_progress.demo import DEMO_CONFIGS
from apps.bambu_progress.icons import APP
from apps.bambu_progress.ui import Ui


def test_parse_args_defaults():
    a = parse_args([])
    assert a.host is None and a.demo is False and a.once is False
    assert a.config == Path(__file__).resolve().parents[1] / "printers.toml"
    b = parse_args(["--demo", "--host", "1.2.3.4", "--once"])
    assert (b.demo, b.host, b.once) == (True, "1.2.3.4", True)
    assert DEMO_HOST == "127.0.0.1:8080"


class FakeBar:
    def __init__(self, draw_error=None):
        self.draws = []
        self.clears = 0
        self.sounds = []
        self.draw_error = draw_error
        self.ws_messages = []
        self.ws_rounds = 0

    async def display_draw(self, elements):
        if self.draw_error:
            raise self.draw_error
        self.draws.append(elements)

    async def display_clear(self, **kw):
        assert kw["application_name"] == APP
        self.clears += 1

    async def audio_play(self, *, stock_path, application_name):
        self.sounds.append(stock_path)

    async def stream_status_ws(self):
        self.ws_rounds += 1
        for m in self.ws_messages:
            yield m
        raise exceptions.BusyBarWebSocketError("closed")


async def test_render_loop_once_draws_current_ui():
    bar = FakeBar()
    ui = Ui(DEMO_CONFIGS)
    queue: asyncio.Queue = asyncio.Queue()
    st = PrinterState(name="P1S-A", connection=Connection.ONLINE, gcode_state=GcodeState.RUNNING, percent=10, last_report_at=1.0)
    queue.put_nowait((0, st))
    await render_loop(bar, ui, queue, once=True)
    assert len(bar.draws) == 1 and ui.states[0].percent == 10
    assert bar.draws[0].application_name == APP


async def test_render_loop_plays_sound_and_ignores_409():
    bar = FakeBar()
    ui = Ui(DEMO_CONFIGS)
    queue: asyncio.Queue = asyncio.Queue()
    on = PrinterState(name="P1S-A", connection=Connection.ONLINE, gcode_state=GcodeState.RUNNING, last_report_at=1.0)
    ui.apply_update(0, on)
    from dataclasses import replace

    queue.put_nowait((0, replace(on, gcode_state=GcodeState.FINISH, percent=100)))
    await render_loop(bar, ui, queue, once=True)
    assert bar.sounds == ["shared/sounds/calendar_event_starts.snd"]

    busy = FakeBar(draw_error=exceptions.BusyBarAPIError("busy", status_code=409))
    await render_loop(busy, Ui(DEMO_CONFIGS), asyncio.Queue(), once=True)  # must not raise


async def test_render_loop_clears_once_when_hidden():
    bar = FakeBar()
    ui = Ui(DEMO_CONFIGS)
    ui.handle_input("button", "back")
    await render_loop(bar, ui, asyncio.Queue(), once=True)
    await render_loop(bar, ui, asyncio.Queue(), once=True)
    assert bar.draws == [] and bar.clears >= 1


async def test_input_loop_feeds_ui_and_reconnects(monkeypatch):
    bar = FakeBar()
    bar.ws_messages = [{"updates": [{"input": {"encoder_event": {"delta": 1}}}]}]
    ui = Ui(DEMO_CONFIGS)
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("apps.bambu_progress.app.asyncio.sleep", fake_sleep)
    try:
        await input_loop(bar, ui)
    except asyncio.CancelledError:
        pass
    assert ui.selected == 2  # two rounds of the same message: 0 -> 1 -> 2
    assert bar.ws_rounds == 2 and sleeps == [5.0, 5.0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest apps/bambu_progress/tests/test_app.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement app.py**

```python
"""BUSY Bar app: pick a Bambu Lab printer with the dial, watch its progress.

    python -m apps.bambu_progress.app                       # USB bar, printers.toml
    python -m apps.bambu_progress.app --demo                # emulator at 127.0.0.1:8080, fake printers
    python -m apps.bambu_progress.app --host 192.168.1.20 --token 1234
    python -m apps.bambu_progress.app --demo --once         # draw one frame and exit
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
import time
from pathlib import Path

from busylib import AsyncBusyBar, exceptions

from .bambu import PrinterMonitor
from .config import ConfigError, load_config
from .demo import DEMO_CONFIGS, DemoMonitor
from .icons import APP, ensure_uploaded, required_icons
from .ui import Ui, parse_input_events

TICK = 0.5          # seconds between draws (max 2 draws/s)
RECONNECT = 5.0     # seconds before re-opening the bar's input stream
DEMO_HOST = "127.0.0.1:8080"

log = logging.getLogger("bambu-progress")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="bambu-progress", description="Bambu Lab print progress on a BUSY Bar")
    p.add_argument("--host", help="bar address (default: printers.toml or 10.0.4.20; --demo: 127.0.0.1:8080)")
    p.add_argument("--token", help="bar access PIN / API token (overrides printers.toml)")
    p.add_argument("--config", type=Path, default=Path(__file__).resolve().with_name("printers.toml"))
    p.add_argument("--demo", action="store_true", help="fake printers; no printers.toml needed")
    p.add_argument("--once", action="store_true", help="draw one frame and exit")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


async def input_loop(bar: AsyncBusyBar, ui: Ui) -> None:
    while True:
        try:
            async for message in bar.stream_status_ws():
                if isinstance(message, dict):
                    for kind, value in parse_input_events(message):
                        ui.handle_input(kind, value)
        except exceptions.BusyBarError as exc:
            log.warning("input stream lost (%s); retry in %.0fs", exc, RECONNECT)
        await asyncio.sleep(RECONNECT)


async def render_loop(bar: AsyncBusyBar, ui: Ui, queue: asyncio.Queue, *, once: bool = False) -> None:
    cleared = False
    while True:
        while not queue.empty():
            index, state = queue.get_nowait()
            ui.apply_update(index, state)
        now = time.monotonic()
        ui.tick(now)
        elements = ui.render(now)
        try:
            if elements is None:
                if not cleared:
                    await bar.display_clear(application_name=APP)
                    cleared = True
            else:
                await bar.display_draw(elements)
                cleared = False
            sound = ui.pop_sound()
            if sound:
                await bar.audio_play(stock_path=sound, application_name=APP)
        except exceptions.BusyBarAPIError as exc:
            if exc.status_code != 409:  # 409: another app owns the screen; try again next tick
                log.warning("bar API error: %s", exc)
        except exceptions.BusyBarError as exc:
            log.warning("bar unreachable: %s", exc)
        if once:
            return
        await asyncio.sleep(TICK)


async def main_async(args: argparse.Namespace) -> None:
    if args.demo:
        configs, host, token = DEMO_CONFIGS, args.host or DEMO_HOST, args.token
    else:
        cfg = load_config(args.config)
        configs, host, token = cfg.printers, args.host or cfg.host, args.token or cfg.token

    queue: asyncio.Queue = asyncio.Queue()
    ui = Ui(configs)
    bar = AsyncBusyBar(host, token=token)
    tasks: list[asyncio.Task] = []
    try:
        version = await bar.version()
        log.info("BUSY Bar at %s, API %s", host, version.api_semver or "unknown")
        uploaded = await ensure_uploaded(bar, required_icons(configs))
        log.info("icons ready (%d uploaded)", len(uploaded))

        monitor_cls = DemoMonitor if args.demo else PrinterMonitor
        tasks = [asyncio.create_task(monitor_cls(i, c, queue).run(), name=c.name) for i, c in enumerate(configs)]
        if args.once:
            await asyncio.sleep(1.0)
            await render_loop(bar, ui, queue, once=True)
            return
        tasks.append(asyncio.create_task(input_loop(bar, ui), name="input"))
        tasks.append(asyncio.create_task(render_loop(bar, ui, queue), name="render"))
        print(f"{APP} → {'demo' if args.demo else f'{len(configs)} printers'} on {host}  (Ctrl-C to stop)")
        await asyncio.gather(*tasks)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if not args.once:
            with contextlib.suppress(Exception):
                await bar.display_clear(application_name=APP)
        await bar.aclose()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main_async(args))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        sys.exit(2)
    except exceptions.BusyBarError as exc:
        print(f"BUSY Bar error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
```

`apps/bambu_progress/manifest.yaml`:
```yaml
name: Bambu Progress
author: Keyrnaker
description: Pick one of your Bambu Lab printers with the dial and watch its progress bar, remaining time, and finish/pause/error alerts. Local MQTT, no cloud.
tags:
  - 3d-printing
  - bambu
  - progress
preview: ./preview.png
```

Append to the project root `README.md`:
```markdown
## apps/bambu_progress

Bambu Lab 프린터 3대의 출력 진행 상태를 다이얼로 골라 보는 앱. 설계: `docs/superpowers/specs/2026-09-24-bambu-progress-design.md`

```bash
cp apps/bambu_progress/printers.example.toml apps/bambu_progress/printers.toml   # IP/시리얼/액세스 코드 입력
.venv/bin/python -m apps.bambu_progress.app                # USB로 연결한 실기기
.venv/bin/python -m apps.bambu_progress.app --demo         # 에뮬레이터(127.0.0.1:8080) + 가짜 프린터
.venv/bin/pytest -q                                        # 단위 테스트
```

조작: 다이얼로 프린터 선택, OK로 상세, BACK으로 목록/숨김. 완료·일시정지·에러는 소리와 함께 알림.
```

- [ ] **Step 4: Run all tests**

Run: `.venv/bin/pytest -q`
Expected: all pass (`test_app.py`: `5 passed`)

- [ ] **Step 5: Smoke-run the CLI without a bar**

Run: `.venv/bin/python -m apps.bambu_progress.app --demo --host 127.0.0.1:9 --once; echo "exit=$?"`
Expected: prints `BUSY Bar error: …` (connection refused) and `exit=1`. No traceback.

Run: `.venv/bin/python -m apps.bambu_progress.app --config /nonexistent.toml; echo "exit=$?"`
Expected: `config error: config file not found: /nonexistent.toml` and `exit=2`.

- [ ] **Step 6: Commit**

```bash
git add apps/bambu_progress/app.py apps/bambu_progress/manifest.yaml apps/bambu_progress/tests/test_app.py README.md
git commit -m "feat(bambu-progress): CLI entry point, render/input loops, manifest

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Verify on the emulator

**Files:**
- Uses: `scripts/setup-emulator.sh`, `scripts/run-emulator.sh` (already in repo)
- Create: `apps/bambu_progress/preview.png` (captured from the emulator)

- [ ] **Step 1: Build and start the emulator**

```bash
cd ~/Workspace/busybar
./scripts/setup-emulator.sh          # first time only; clones + npm install + build
./scripts/run-emulator.sh &          # serves http://127.0.0.1:8080
sleep 3 && curl -s http://127.0.0.1:8080/api/version
```
Expected: JSON containing `"api_semver"`.

- [ ] **Step 2: Single frame**

```bash
.venv/bin/python -m apps.bambu_progress.app --demo --once -v
```
Expected: log lines `BUSY Bar at 127.0.0.1:8080, API 25.0.0` and `icons ready (26 uploaded)`; exit 0. In the browser the list screen shows two rows (P1S-A selected in mint, P1S-B dim) with printer icons and `0%` labels.

- [ ] **Step 3: Full demo run and checklist**

```bash
.venv/bin/python -m apps.bambu_progress.app --demo
```
In the browser at http://127.0.0.1:8080, verify each item and note anything off:
- [ ] List: dial (the emulator's encoder buttons) moves the highlight, wraps 3 → 1, and the third printer appears alone on a second page.
- [ ] OK opens the detail screen: name, bold percent, `Nh Nm left`, 3 px bar in the printer's colour, nozzle icon toggling each half second.
- [ ] Dial on detail switches printers directly; BACK returns to the list; BACK again blanks the screen; any button restores the list.
- [ ] Within ~40 s P1S-B pauses: yellow notice `P1S-B / FILAMENT` with the reminder sound, gone after 8 s, then the detail bar blinks yellow if P1S-B is selected.
- [ ] X1C fails: red notice with the HMS code; stays until a button is pressed; dial press dismisses without changing selection.
- [ ] P1S-A finishes: green `DONE` notice with the event sound; detail shows the check icon and the scrolling task name.
- [ ] Ctrl-C clears the screen and prints `stopped`.

- [ ] **Step 4: Capture preview.png**

In the emulator page, with the detail screen of a running printer showing, click the PNG capture button; save the file as `apps/bambu_progress/preview.png` (720×160).

- [ ] **Step 5: Fix anything the checklist surfaced, re-run tests, commit**

```bash
.venv/bin/pytest -q
git add apps/bambu_progress/preview.png apps
git commit -m "feat(bambu-progress): emulator-verified, add preview

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

- [ ] **Step 6: Real hardware (when the bar and a printer are available)**

```bash
cp apps/bambu_progress/printers.example.toml apps/bambu_progress/printers.toml
# fill in ip / serial / access_code for each printer, then:
.venv/bin/python -m apps.bambu_progress.app -v
```
Expected: within a few seconds each printer row leaves `...`/`connecting`; an idle printer shows the dot; a printing one shows its percent. If a row shows `AUTH`, re-check that printer's access code (it is case-sensitive and changes when LAN mode is reset).

---

## Self-review notes

- Spec §3.1–3.3 → Tasks 5, 6. §3.4 icons → Task 4. §4 components → Tasks 1–9 one-to-one with the module table. §5 error handling → Task 7 (MQTT), Task 9 (bar 409/unreachable, config exit code 2), Task 2 (bad fields). §6 tests → each task's tests plus Task 10 manual checklist. §7 dependencies → Task 1.
- Interface names are consistent across tasks: `PrinterState`, `Connection`, `GcodeState`, `parse_report`, `effective_connection`, `Event`, `EventKind`, `detect`, `icon_filename`, `required_icons`, `ensure_uploaded`, `visual`, `render_list/detail/notice`, `Ui`, `parse_input_events`, `PrinterMonitor`, `DemoMonitor`, `render_loop`, `input_loop`.
- Review Focus tests are pinned: (1) `test_parse_report_merges_delta`, (2) `test_parse_report_coerces_percent`, (3) `test_no_event_on_first_report`, (4) `test_input_during_notice_dismisses_only`, (5) `test_list_window_small_counts` + `test_encoder_wraps_with_two_printers`.
- Known approximation: filament run-out is detected by the HMS module prefix `0700` (AMS). If a real printer reports it under another module, the pause notice still fires, just with the message `PAUSED` instead of `FILAMENT`.
