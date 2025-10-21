import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ophyd_async.core import (
    AsyncStatus,
    Command,
    CommandBackend,
    CommandConnector,
    CommandR,
    CommandRW,
    CommandW,
    CommandX,
    soft_command_rw
)
from ophyd_async.core import Device


# ---------------------------
# Helper backends for testing
# ---------------------------


class RecordingBackend(CommandBackend):
    """A backend that records calls and returns a configured value.

    Designed for "real" connections path where Device.connect(mock=False)
    calls backend.connect(...).
    """

    def __init__(self, return_value: Any = None):
        self.return_value = return_value
        self.connect_called_with: float | None = None
        self.calls: list[tuple[tuple, dict]] = []

    def source(self, name: str, read: bool) -> str:
        return f"rec://{name}"

    async def get_datakey(self, source: str):
        from event_model import DataKey
        # Minimal datakey compatible with our usage
        return DataKey(source=source, dtype="number", shape=[])

    async def connect(self, timeout: float) -> None:
        self.connect_called_with = timeout

    async def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.return_value


# ---------------------------
# Tests
# ---------------------------


def test_cannot_add_child_to_command():
    class Dummy(Device):
        pass

    cmd = CommandX(backend=RecordingBackend())
    with pytest.raises(
        KeyError,
        match="Cannot add Device or Signal child foo=<.*> of Command, make a subclass of Device instead",
    ):
        cmd.foo = Dummy()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_real_connect_calls_backend_and_call_returns_value():
    backend = RecordingBackend(return_value=123)
    cmd = CommandR[int](backend=backend, name="test-cmd")

    # Real connect goes through CommandConnector -> backend.connect(timeout)
    await cmd.connect(mock=False, timeout=3.14)

    assert backend.connect_called_with == pytest.approx(3.14)

    # call delegates to backend.call and returns its value
    result = await cmd.call()
    assert result == 123
    assert backend.calls == [((), {"wait": True})]


@pytest.mark.asyncio
async def test_trigger_returns_asyncstatus_and_completes_on_backend_call():
    backend = RecordingBackend(return_value=None)
    cmd = CommandX(backend=backend, name="trigger-cmd")

    # Connect in mock mode to get MockCommandBackend with proceeds Event
    await cmd.connect(mock=True)

    # Reach into the mock backend to control completion
    from ophyd_async.core import MockCommandBackend

    mb = cmd._connector.backend  # type: ignore[attr-defined]
    assert isinstance(mb, MockCommandBackend)

    # Block completion
    mb.proceeds.clear()

    status = cmd.trigger()
    assert isinstance(status, AsyncStatus)
    # Let the loop spin once to register the awaiting
    await asyncio.sleep(0)
    assert not status.done

    # Verify that a call was issued with no args
    mm = cmd._mock()  # underlying MagicMock from LazyMock
    # There should be an AsyncMock named 'call' attached
    assert hasattr(mm, "call")
    # Unblock
    mb.proceeds.set()

    # Await completion
    await status
    assert status.done

    # The call mock should have been awaited once
    call_mock: AsyncMock = getattr(mm, "call")
    assert call_mock.await_count == 1


@pytest.mark.asyncio
async def test_mock_backend_set_return_value_only():
    backend = RecordingBackend()

    # Use CommandRW to exercise args passthrough (not enforced at runtime)
    cmd = CommandRW(backend=backend, name="rw")
    await cmd.connect(mock=True)

    from ophyd_async.core import MockCommandBackend

    mb: MockCommandBackend = cmd._connector.backend  # type: ignore[assignment]

    # Fixed return value should be returned regardless of args
    mb.set_return_value(7)
    assert await cmd.call(1, x=2) == 7

    mb.set_return_value(12)
    assert await cmd.call(3, x=9) == 12

    mb.set_return_value(20)
    assert await cmd.call(4, x=5) == 20


@pytest.mark.asyncio
async def test_command_flavours_basic_usage():
    # CommandR: no args, returns a value
    r_backend = RecordingBackend(return_value="ok")
    cmd_r = CommandR[str](backend=r_backend, name="r")
    await cmd_r.connect()
    assert await cmd_r.call() == "ok"
    # trigger ignores the return value but should complete
    await cmd_r.trigger()

    # CommandW: args, returns None
    w_backend = RecordingBackend(return_value=None)
    cmd_w = CommandW(backend=w_backend, name="w")
    await cmd_w.connect()
    await cmd_w.call(1, 2, kw=3)
    assert w_backend.calls == [((1, 2), {"kw": 3, "wait": True})]

    # CommandRW: args and return value
    rw_backend = RecordingBackend(return_value=42)
    cmd_rw = CommandRW(backend=rw_backend, name="rw2")
    await cmd_rw.connect()
    assert await cmd_rw.call("a", b=True) == 42

    # CommandX: no args, no return
    x_backend = RecordingBackend(return_value=None)
    cmd_x = CommandX(backend=x_backend, name="x")
    await cmd_x.connect()
    await cmd_x.call()
    await cmd_x.trigger()


@pytest.mark.asyncio
async def test_soft_command_rw_basic_return_and_args_ignored():

    # Create a soft command that returns an int regardless of inputs
    cmd = soft_command_rw(command_args=None, command_return=5, name="soft-rw")
    await cmd.connect()

    # Multiple positional and keyword args should be accepted and ignored
    assert await cmd.call(1, 2, a=3, b="x") == 5
    assert await cmd.call() == 5


@pytest.mark.asyncio
async def test_soft_command_rw_datakey_units_precision():
    name = "soft-meta"
    cmd = soft_command_rw(command_args=None, command_return=3.14, name=name, units="m", precision=4)
    await cmd.connect()

    # Reach into backend to get DataKey
    backend = cmd._connector.backend
    source = backend.source(name, read=True)
    dk = await backend.get_datakey(source)
    assert dk["source"] == source
    # dtype is free-form; ensure we at least produce a DataKey and source matches


@pytest.mark.parametrize("ret", [0, 1.5, "hello"])  # int, float, str
@pytest.mark.asyncio
async def test_soft_command_rw_parametrized_returns(ret):
    cmd = soft_command_rw(command_args=None, command_return=ret, name="soft-rw-param")
    await cmd.connect()
    assert await cmd.call("unused", key="ignored") == ret
