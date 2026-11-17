import asyncio
import inspect
import logging
import time
from unittest.mock import AsyncMock, Mock

import pytest
from aioca import CANothing
from epicscorelibs.ca import cadef, dbr
from p4p.client.raw import Disconnected, Finished, RemoteError
from p4p.nt import NTScalar

from ophyd_async.epics.core import epics_signal_r


@pytest.fixture(params=["ca", "pva"])
async def monitor(request, monkeypatch):
    protocol = request.param
    transport = Mock()
    if protocol == "ca":

        def make_value(value, timestamp, severity):
            result = dbr.ca_float(value)
            result.ok = True
            result.datatype = dbr.DBR_DOUBLE
            result.element_count = 1
            result.timestamp = timestamp
            result.severity = severity
            return result

        monkeypatch.setattr(
            "ophyd_async.epics.core._aioca.caget",
            AsyncMock(return_value=make_value(0.0, 1.0, 0)),
        )
        monkeypatch.setattr("ophyd_async.epics.core._aioca.camonitor", transport)
        disconnected = CANothing("test", cadef.ECA_DISCONN)
    else:

        def make_value(value, timestamp, severity):
            return NTScalar("d").wrap(value, timestamp=timestamp, severity=severity)

        context = Mock(get=AsyncMock(return_value=make_value(0.0, 1.0, 0)))
        context.monitor = transport
        monkeypatch.setattr("ophyd_async.epics.core._p4p.context", lambda: context)
        disconnected = Disconnected()

    signal = epics_signal_r(float, f"{protocol}://test", name="test")
    await signal.connect()

    async def send(value):
        result = transport.call_args.args[1](value)
        if inspect.isawaitable(result):
            await result

    return signal, transport, send, make_value, disconnected


async def test_monitor_requests_disconnect_notifications(monitor):
    signal, transport, _, _, _ = monitor
    callback = Mock()
    signal.subscribe_reading(callback)
    try:
        assert transport.call_args.kwargs["notify_disconnect"] is True
    finally:
        signal.clear_sub(callback)
    transport.return_value.close.assert_called_once_with()


@pytest.mark.parametrize("staged", [False, True])
async def test_disconnect_retains_value_and_reconnect_restores_reading(monitor, staged):
    signal, _, send, make_value, disconnected = monitor
    callback = Mock()
    if staged:
        await signal.stage()
    signal.subscribe_reading(callback)
    try:
        await send(make_value(12.5, 100.25, 1))
        first = {"test": {"value": 12.5, "timestamp": 100.25, "alarm_severity": 1}}
        callback.assert_called_once_with(first)
        initial_reading = callback.call_args.args[0]

        before = time.time()
        await send(disconnected)
        after = time.time()
        reading = callback.call_args.args[0]
        assert reading["test"]["value"] == 12.5
        assert reading["test"]["alarm_severity"] == -1
        assert before <= reading["test"]["timestamp"] <= after
        assert initial_reading == first
        assert await signal.read(cached=True) == reading
        assert await signal.get_value() == 12.5
        assert await signal.read(cached=False) == {
            "test": {"value": 0.0, "timestamp": 1.0, "alarm_severity": 0}
        }

        await send(make_value(23.5, 200.5, 2))
        restored = {"test": {"value": 23.5, "timestamp": 200.5, "alarm_severity": 2}}
        callback.assert_called_with(restored)
        assert callback.call_count == 3
        assert await signal.read(cached=True) == restored
    finally:
        signal.clear_sub(callback)
        if staged:
            await signal.unstage()


async def test_initial_disconnect_does_not_make_cache_valid(monitor):
    signal, _, send, make_value, disconnected = monitor
    callback = Mock()
    signal.subscribe_reading(callback)
    try:
        await send(disconnected)
        callback.assert_not_called()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(signal.read(cached=True), timeout=0.01)
        await send(make_value(12.5, 100.25, 0))
        assert await signal.read(cached=True) == {
            "test": {"value": 12.5, "timestamp": 100.25, "alarm_severity": 0}
        }
    finally:
        signal.clear_sub(callback)


async def test_resubscribing_does_not_reuse_previous_reading(monitor):
    signal, transport, send, make_value, disconnected = monitor
    callback = Mock()
    signal.subscribe_reading(callback)
    try:
        await send(make_value(12.5, 100.25, 0))
    finally:
        signal.clear_sub(callback)
    callback.reset_mock()
    signal.subscribe_reading(callback)
    try:
        await send(disconnected)
        callback.assert_not_called()
        await send(make_value(23.5, 200.5, 0))
        callback.assert_called_once_with(
            {"test": {"value": 23.5, "timestamp": 200.5, "alarm_severity": 0}}
        )
    finally:
        signal.clear_sub(callback)
    assert transport.return_value.close.call_count == 2


@pytest.mark.parametrize("monitor", ["pva"], indirect=True)
@pytest.mark.parametrize("error", [RemoteError("remote error"), Finished()])
async def test_other_pva_monitor_errors_are_logged_without_a_reading(
    monitor, error, caplog
):
    signal, _, send, make_value, _ = monitor
    callback = Mock()
    signal.subscribe_reading(callback)
    try:
        await send(make_value(12.5, 100.25, 0))
        first = await signal.read(cached=True)
        with caplog.at_level(logging.INFO, logger="ophyd_async"):
            await send(error)
        callback.assert_called_once_with(first)
        assert await signal.read(cached=True) == first
        assert "test" in caplog.text
        assert repr(error) in caplog.text
    finally:
        signal.clear_sub(callback)
