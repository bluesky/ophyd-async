import pytest

pytestmark = pytest.mark.timeout(8.0)

from ophyd_async.core import (
    AsyncStatus,
    CommandR,
    CommandRW,
    CommandW,
    CommandX,
    StrictEnum,
)
from ophyd_async.tango.core import TangoCommandBackend, get_full_attr_trl
from test_base_device import TestDevice


@pytest.fixture(scope="module")
def tango_test_device(subprocess_helper):
    with subprocess_helper(
        [{"class": TestDevice, "devices": [{"name": "test/device/1"}]}]
    ) as context:
        yield context.trls["test/device/1"]


class MsgEnum(StrictEnum):
    A = "A"
    B = "B"


@pytest.mark.asyncio
async def test_execute_command_completes(tango_test_device: str):
    # EXECUTE: no input, no output
    backend = TangoCommandBackend(get_full_attr_trl(tango_test_device, "clear"))
    cmd = CommandX(backend=backend, name="clear-cmd")
    await cmd.connect()

    # call() should just complete and return None
    assert await cmd.call() is None

    # trigger() should return an AsyncStatus that completes
    status = cmd.trigger()
    assert isinstance(status, AsyncStatus)
    await status
    assert status.done and status.success


@pytest.mark.asyncio
async def test_read_only_command_returns_value(tango_test_device: str):
    # READ: no input, returns a value
    backend = TangoCommandBackend(get_full_attr_trl(tango_test_device, "get_msg"))
    cmd = CommandR[str](backend=backend, name="get-msg")
    await cmd.connect()

    val = await cmd.call()
    # default message set in TestDevice
    assert isinstance(val, str)
    assert val  # non-empty

    # trigger ignores return but must complete
    await cmd.trigger()


@pytest.mark.asyncio
async def test_write_only_command_side_effect(tango_test_device: str):
    # WRITE: input, no return; verify side-effect via read-only command
    set_backend = TangoCommandBackend(get_full_attr_trl(tango_test_device, "set_msg"))
    set_cmd = CommandW(backend=set_backend, name="set-msg")

    get_backend = TangoCommandBackend(get_full_attr_trl(tango_test_device, "get_msg"))
    get_cmd = CommandR[str](backend=get_backend, name="get-msg")

    await set_cmd.connect()
    await get_cmd.connect()

    await set_cmd.call("World")
    assert await get_cmd.call() == "World"


@pytest.mark.asyncio
async def test_read_write_command_round_trip(tango_test_device: str):
    # READ_WRITE: input and output
    backend = TangoCommandBackend(get_full_attr_trl(tango_test_device, "echo"))
    cmd = CommandRW(backend=backend, name="echo")
    await cmd.connect()

    payload = "hello tango"
    assert await cmd.call(payload) == payload


@pytest.mark.asyncio
async def test_enum_command_with_converter(tango_test_device: str):
    # Provide StrictEnum type so the backend installs a TangoEnumConverter
    backend = TangoCommandBackend(
        get_full_attr_trl(tango_test_device, "enum_cmd"),
        datatype=MsgEnum,
    )
    cmd = CommandRW(backend=backend, name="enum-cmd")
    await cmd.connect()

    # Pass a StrictEnum member (a str subclass); expect string label back
    assert await cmd.call(MsgEnum.A) == MsgEnum.A.value
    assert await cmd.call(MsgEnum.B) == MsgEnum.B.value


@pytest.mark.asyncio
async def test_command_error_propagation(tango_test_device: str):
    backend = TangoCommandBackend(get_full_attr_trl(tango_test_device, "raise_exception_cmd"))
    cmd = CommandX(backend=backend, name="boom")
    await cmd.connect()

    with pytest.raises(Exception):
        await cmd.call()


@pytest.mark.asyncio
async def test_kwargs_not_supported(tango_test_device: str):
    backend = TangoCommandBackend(get_full_attr_trl(tango_test_device, "echo"))
    cmd = CommandRW(backend=backend, name="echo")
    await cmd.connect()

    with pytest.raises(TypeError):
        await cmd.call(value="x")



@pytest.mark.asyncio
async def test_helpers_execute_command_x(tango_test_device: str):
    # Use tango_command_x factory to create an EXECUTE command (no args, no return)
    from ophyd_async.tango.core import tango_command_x

    cmd = tango_command_x(get_full_attr_trl(tango_test_device, "clear"), name="clear-x")
    await cmd.connect()

    # call returns None
    assert await cmd.call() is None

    # trigger returns a Status and completes successfully
    status = cmd.trigger()
    assert isinstance(status, AsyncStatus)
    await status
    assert status.done and status.success


@pytest.mark.asyncio
async def test_helpers_read_only_r(tango_test_device: str):
    # Use tango_command_r factory to create a READ command (no args, returns value)
    from ophyd_async.tango.core import tango_command_r

    cmd = tango_command_r(str, get_full_attr_trl(tango_test_device, "get_msg"), name="get-msg-r")
    await cmd.connect()

    val = await cmd.call()
    assert isinstance(val, str)
    assert val


@pytest.mark.asyncio
async def test_helpers_write_only_w(tango_test_device: str):
    # Use tango_command_w to set a value, and verify via tango_command_r
    from ophyd_async.tango.core import tango_command_r, tango_command_w

    set_cmd = tango_command_w(str, get_full_attr_trl(tango_test_device, "set_msg"), name="set-msg-w")
    get_cmd = tango_command_r(str, get_full_attr_trl(tango_test_device, "get_msg"), name="get-msg-r")

    await set_cmd.connect()
    await get_cmd.connect()

    await set_cmd.call("via-helper")
    assert await get_cmd.call() == "via-helper"


@pytest.mark.asyncio
async def test_helpers_read_write_rw(tango_test_device: str):
    # Use tango_command_rw factory for an echo command
    from ophyd_async.tango.core import tango_command_rw

    cmd = tango_command_rw(get_full_attr_trl(tango_test_device, "echo"), name="echo-rw")
    await cmd.connect()

    payload = "roundtrip"
    assert await cmd.call(payload) == payload


class MsgEnum2(StrictEnum):
    A = "A"
    B = "B"


@pytest.mark.asyncio
async def test_helpers_enum_rw(tango_test_device: str):
    # Use tango_command_rw with a StrictEnum to exercise the TangoEnumConverter
    from ophyd_async.tango.core import tango_command_rw

    cmd = tango_command_rw(
        get_full_attr_trl(tango_test_device, "enum_cmd"),
        datatype=MsgEnum2,
        name="enum-rw",
    )
    await cmd.connect()

    assert await cmd.call(MsgEnum2.A) == MsgEnum2.A.value
    assert await cmd.call(MsgEnum2.B) == MsgEnum2.B.value
