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


class SilentClient(FakeClient):
    """Connects fine but never delivers a message (printer accepted us while still booting)."""

    async def _gen(self):
        await asyncio.Event().wait()
        yield  # pragma: no cover


async def test_silent_session_is_dropped_and_reopened(caplog):
    import logging

    queue: asyncio.Queue = asyncio.Queue()
    sleeps: list[float] = []
    clients = iter([SilentClient([]), FakeClient([json.dumps({"print": {"mc_percent": 7}}).encode()])])
    mon = PrinterMonitor(0, CFG, queue, client_factory=lambda cfg: next(clients), sleep=make_sleep(sleeps, 2),
                         report_timeout=0.05)
    with caplog.at_level(logging.WARNING, logger="apps.bambu_progress.bambu"):
        with pytest.raises(Stop):
            await mon.run()
    conns = [s.connection for _, s in drain(queue)]
    assert conns == [Connection.CONNECTING, Connection.OFFLINE, Connection.CONNECTING, Connection.ONLINE, Connection.OFFLINE]
    assert any("no report for 0s" in r.message for r in caplog.records)
    assert sleeps == [2.0, 2.0]          # the zombie session costs one short backoff, then the retry works


def test_is_auth_error_variants():
    assert is_auth_error(aiomqtt.MqttError("Connection Refused: not authorised."))
    assert is_auth_error(aiomqtt.MqttError("[code:135] Not authorized"))
    assert not is_auth_error(aiomqtt.MqttError("timed out"))
    assert is_auth_error(aiomqtt.MqttCodeError(5, "connect"))
    assert is_auth_error(aiomqtt.MqttCodeError(4, "connect"))
    assert is_auth_error(aiomqtt.MqttCodeError(SimpleNamespace(value=134), "connect"))
    assert is_auth_error(aiomqtt.MqttError("Connection Refused: bad user name or password."))
