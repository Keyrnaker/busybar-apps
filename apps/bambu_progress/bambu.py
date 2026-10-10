"""Bambu Lab printer state: report parsing now, MQTT monitor in the same file."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import ssl
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

import aiomqtt

from .config import PrinterConfig

log = logging.getLogger(__name__)

# A quiet P1/A1 reports only on change; the periodic pushall is what proves it is
# alive, so the stale threshold must comfortably outlast one pushall period.
PUSHALL_EVERY = 120.0
STALE_AFTER = 300.0
# A healthy session answers every pushall. A printer that was still booting when we connected can
# accept the connection and then never deliver a report (seen on an A1 after a power cycle); such a
# zombie session is dropped and reopened after this much silence.
REPORT_TIMEOUT = PUSHALL_EVERY + 30.0

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


# --- MQTT monitor --------------------------------------------------------------

MQTT_PORT = 8883
MQTT_USER = "bblp"


class AuthError(Exception):
    """The printer rejected the access code. Do not retry."""


def is_auth_error(exc: BaseException) -> bool:
    rc = getattr(exc, "rc", None)
    rc_value = getattr(rc, "value", rc)
    # CONNACK 3.1.1: 4 = bad user name or password, 5 = not authorized.
    # MQTT 5 reason codes (paho 2 maps the old ones onto these): 134, 135.
    if rc_value in (4, 5, 134, 135):
        return True
    text = str(exc).lower()
    return "not authori" in text or "bad user" in text


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
        pushall_every: float = PUSHALL_EVERY,
        report_timeout: float = REPORT_TIMEOUT,
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
        self.report_timeout = report_timeout
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
            log.info("%s: connected, waiting for reports", self.cfg.name)
            pusher = asyncio.create_task(self._pushall_loop(client))
            try:
                messages = client.messages.__aiter__()
                while True:
                    try:
                        message = await asyncio.wait_for(messages.__anext__(), self.report_timeout)
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        raise RuntimeError(f"no report for {self.report_timeout:.0f}s") from None
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
