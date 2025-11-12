import asyncio
import inspect
import types
import pytest
from typing import Any
from unittest.mock import MagicMock

from ophyd_async.core._command import (
    Command,
    CommandBackend,
    CommandConnector,
    CommandR,
    CommandRW,
    CommandW,
    CommandX,
    ConnectionError,
    ConnectionTimeoutError,
    ExecutionError,
    MockCommandBackend,
    SoftCommandBackend,
    _default_of,
    soft_command_r,
    soft_command_rw,
    soft_command_w,
    soft_command_x,
)
from ophyd_async.core._device import Device
from ophyd_async.core._utils import LazyMock


class DummyBackend(CommandBackend):
    """Simple test backend with configurable behaviors."""

    def __init__(self, on_connect: Any | None = None, on_call: Any | None = None):
        # store callables or values/exceptions
        self.on_connect = on_connect
        self.on_call = on_call
        # Provide attributes used by MockCommandBackend when wrapping
        self._command_args = []
        self._command_return_type = object

    def source(self, name: str, read: bool) -> str:
        return f"dummy://{name}:{'r' if read else 'w'}"

    async def get_datakey(self, source: str):
        # Minimal DataKey using make_datakey via a Soft backend to avoid reimpl
        return await SoftCommandBackend([], object, lambda: None).get_datakey(source)

    async def connect(self, timeout: float) -> None:
        if isinstance(self.on_connect, Exception):
            raise self.on_connect
        if callable(self.on_connect):
            res = self.on_connect(timeout)
            if inspect.isawaitable(res):
                await res
            return
        # default: no-op
        return None

    async def call(self, *args, **kwargs):
        oc = self.on_call
        if isinstance(oc, Exception):
            raise oc
        if callable(oc):
            res = oc(*args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res
        return None


@pytest.mark.asyncio
async def test_children_not_allowed_on_command():
    # The Command class uses a dict-like that forbids adding children
    backend = SoftCommandBackend([], type(None), lambda: None)
    cmd = Command(backend, name="cmd")
    with pytest.raises(KeyError) as ex:
        # Access the special mapping and try to insert
        cmd._child_devices["child"] = Device()
    assert "Cannot add Device or Signal child" in str(ex.value)
    assert "of Command" in str(ex.value)


@pytest.mark.asyncio
async def test_soft_command_backend_signature_validation_errors():
    # Arg count mismatch
    with pytest.raises(TypeError) as ex1:
        SoftCommandBackend([int, float], int, lambda a: a)
    assert "Number of command_args" in str(ex1.value)

    # Arg type mismatch
    def cb_str(s: str) -> None:  # pragma: no cover - just signature
        return None

    with pytest.raises(TypeError) as ex2:
        SoftCommandBackend([int], type(None), cb_str)
    assert "doesn't match callback parameter type" in str(ex2.value)

    # Return type mismatch
    def cb_ret() -> str:  # pragma: no cover - just signature
        return "x"

    with pytest.raises(TypeError) as ex3:
        SoftCommandBackend([], int, cb_ret)
    assert "doesn't match callback return annotation" in str(ex3.value)


@pytest.mark.asyncio
async def test_soft_command_backend_source_and_connect():
    be = SoftCommandBackend([], int, lambda: 3, units="V", precision=2)
    assert be.source("name", read=True) == "softcmd://name"
    assert await be.connect(0.1) is None


@pytest.mark.asyncio
async def test_soft_command_backend_call_sync_and_async_and_error():
    # Sync callback
    be_sync = SoftCommandBackend([int, int], int, lambda a, b: a + b)
    res = await be_sync.call(2, 5)
    assert res == 7

    # Async callback
    async def async_cb(a: int) -> int:
        await asyncio.sleep(0)
        return a * 2

    be_async = SoftCommandBackend([int], int, async_cb)
    res2 = await be_async.call(6)
    assert res2 == 12

    # Error propagation as ExecutionError, and last_return_value reset to None
    class Boom(Exception):
        pass

    be_err = SoftCommandBackend([], int, lambda: (_ for _ in ()).throw(Boom("kaboom")))
    with pytest.raises(ExecutionError) as ex:
        await be_err.call()
    assert "Command execution failed" in str(ex.value)


@pytest.mark.asyncio
async def test_soft_command_backend_datakey_metadata_with_concrete_type():
    # With a concrete return type, produce a value first so exemplar exists
    be = SoftCommandBackend([], int, lambda: 42, units="Hz", precision=3)
    await be.call()
    dk1 = await be.get_datakey("src")
    assert dk1["source"] == "src"
    assert dk1["units"] == "Hz"
    assert dk1["precision"] == 3
    assert dk1["dtype"] == "integer"


@pytest.mark.asyncio
async def test_soft_command_backend_datakey_uses_last_return_value_to_refine_type():
    # Start with return type object, but set last return to int via a call
    be = SoftCommandBackend([], object, lambda: 42, units="Hz", precision=3)
    # After calling, last_return_value present, dtype updated to int
    await be.call()
    dk2 = await be.get_datakey("src2")
    assert dk2["source"] == "src2"
    # dtype for int is "integer"
    assert dk2["dtype"] == "integer"


@pytest.mark.asyncio
async def test_mock_command_backend_basic_behaviour_and_source_and_connect_and_datakey():
    init = SoftCommandBackend([int, str], int, lambda a, b: 5)
    lz = LazyMock()
    m = MockCommandBackend(init, lz)

    # Source has mock+ prefix
    assert m.source("nm", read=False).startswith("mock+")

    # connect not allowed
    with pytest.raises(RuntimeError):
        await m.connect(0.1)

    # call is recorded and returns from soft backend
    m.set_return_value(9)
    result = await m.call(1, 2)
    assert result == 9
    m.call_mock.assert_awaited()

    # get_datakey returns something sensible (units absent here)
    dk = await m.get_datakey("abc")
    assert dk["source"].endswith("abc")


@pytest.mark.asyncio
async def test_mock_command_backend_proceeds_event_gating_and_cleanup():
    init = SoftCommandBackend([int, str], int, lambda a, b: 1)
    m = MockCommandBackend(init, LazyMock())
    m.set_return_value(123)

    # Stop proceeding and ensure call waits until set
    m.proceeds.clear()

    async def later_set():
        await asyncio.sleep(0.01)
        m.proceeds.set()

    t = asyncio.create_task(m.call())
    await asyncio.sleep(0)
    assert not t.done()
    await later_set()
    assert await t == 123

    # cleanup clears event and resets mock
    _ = m.call_mock  # force creation
    assert m._call_mock is not None
    m.cleanup()
    assert not m.proceeds.is_set()
    assert m._call_mock is not None
    # After cleanup, the mock has been reset (no awaited calls)
    m._call_mock.assert_not_called()


def test_mock_command_backend_reject_double_mock():
    init = SoftCommandBackend([int, str], int, lambda a, b: 1)
    m1 = MockCommandBackend(init, LazyMock())
    with pytest.raises(ValueError):
        _ = MockCommandBackend(m1, LazyMock())


@pytest.mark.asyncio
async def test_command_connector_connect_mock_and_real_and_errors():
    """Test CommandConnector's connect_mock and connect_real methods and error handling."""

    # Create a simple callback for SoftCommandBackend
    async def simple_cb() -> int:
        return 42

    # Create a SoftCommandBackend with matching arguments
    soft_backend = SoftCommandBackend(
        command_args=[],
        command_return=int,
        command_cb=simple_cb
    )

    device = MagicMock(name="dev")
    device.log = MagicMock()
    device.log.debug = MagicMock()

    # Test 1: connect_real should translate timeout to ConnectionTimeoutError
    timeout_backend = DummyBackend(
        on_connect=lambda timeout: asyncio.sleep(timeout * 2)
    )
    conn1 = CommandConnector(timeout_backend)

    with pytest.raises(ConnectionTimeoutError, match="Failed to connect within 0.01 seconds"):
        await conn1.connect_real(device, timeout=0.01, force_reconnect=False)

    # Test 2: Backend raising generic Exception becomes ConnectionError
    err_backend = DummyBackend(
        on_connect=RuntimeError("boom")
    )
    conn2 = CommandConnector(err_backend)

    with pytest.raises(ConnectionError, match="Connection failed: boom"):
        await conn2.connect_real(device, timeout=0.01, force_reconnect=False)

    # Test 3: connect_mock swaps in a MockCommandBackend
    conn3 = CommandConnector(soft_backend)
    mock = LazyMock()
    await conn3.connect_mock(device, mock)
    assert isinstance(conn3.backend, MockCommandBackend)

    # Test 4: connect_real reverts mock to real and calls connect on real backend
    connected = False
    async def mark_connected(timeout):
        nonlocal connected
        connected = True

    real_backend = DummyBackend(on_connect=mark_connected)
    conn4 = CommandConnector(real_backend)
    await conn4.connect_mock(device, LazyMock())
    assert isinstance(conn4.backend, MockCommandBackend)

    await conn4.connect_real(device, timeout=0.05, force_reconnect=False)
    assert conn4.backend is real_backend
    assert connected is True

    # Test 5: cleanup cleans up mock resources
    await conn4.connect_mock(device, LazyMock())
    mb = conn4.backend
    assert isinstance(mb, MockCommandBackend)
    conn4.cleanup()
    assert conn4._mock_backend is None

    # Test 6: Verify that MockCommandBackend properly wraps the backend
    original_backend = DummyBackend()
    conn5 = CommandConnector(original_backend)
    await conn5.connect_mock(device, LazyMock())

    # Verify the mock backend was created with the original backend
    mock_backend = conn5.backend
    assert isinstance(mock_backend, MockCommandBackend)
    assert mock_backend.initial_backend is original_backend

    # Test 7: Verify that call_mock is properly initialized
    assert hasattr(mock_backend, 'call_mock')
    assert mock_backend.call_mock is not None

    # Test 8: Verify that proceeds event is properly initialized
    assert hasattr(mock_backend, 'proceeds')
    assert isinstance(mock_backend.proceeds, asyncio.Event)


@pytest.mark.asyncio
async def test_command_call_and_trigger_success_and_error():
    # Successful call via backend
    be = SoftCommandBackend([int], int, lambda a: a + 1)
    cmd = Command(be, name="adder")
    assert await cmd.call(41) == 42

    # trigger wraps and awaits completion; ignores return value
    status = await cmd.trigger(41)
    # AsyncStatus.wrap returns an Awaitable[None]; awaiting already done above
    assert status is None

    # Error path: backend callback raises -> ExecutionError propagates
    be_err = SoftCommandBackend([], int, lambda: (_ for _ in ()).throw(ValueError("e")))
    cmd_err = Command(be_err, name="boom")
    with pytest.raises(ExecutionError):
        await cmd_err.trigger()


def test_default_of_various_types():
    # Covered typical primitives
    assert _default_of(None) is None
    assert _default_of(bool) is False
    assert _default_of(int) == 0
    assert _default_of(float) == 0
    assert _default_of(str) == ""

    class HasDefault:
        def __init__(self):
            self.x = 1

    v = _default_of(HasDefault)
    assert isinstance(v, HasDefault)

    class NoCtor:
        def __init__(self):
            raise RuntimeError("nope")

    assert _default_of(NoCtor) is None


@pytest.mark.asyncio
async def test_soft_command_factories_happy_paths_and_type_errors():
    # soft_command_r type check
    with pytest.raises(TypeError):
        _ = soft_command_r(123, lambda: 1)  # not a type

    # happy path: r
    cr = soft_command_r(int, lambda: 7, name="r", units="m", precision=1)
    assert isinstance(cr, CommandR)
    assert await cr.call() == 7

    # w
    seen = {}

    def w_cb(a: int, b: str) -> None:
        seen["args"] = (a, b)

    cw = soft_command_w(int, str, command_cb=w_cb, name="w")
    assert isinstance(cw, CommandW)
    assert await cw.call(5, "hi") is None
    assert seen["args"] == (5, "hi")

    # x
    seen_x = {"called": False}

    def x_cb() -> None:
        seen_x["called"] = True

    cx = soft_command_x(x_cb, name="x")
    assert isinstance(cx, CommandX)
    assert await cx.call() is None
    assert seen_x["called"] is True

    # rw type error
    with pytest.raises(TypeError):
        _ = soft_command_rw(int, command_return=123, command_cb=lambda a: a)

    # rw happy
    crw = soft_command_rw(int, command_return=int, command_cb=lambda a: a + 1, name="rw")
    assert isinstance(crw, CommandRW)
    assert await crw.call(4) == 5

