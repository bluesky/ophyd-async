import pytest
import numpy as np
from ophyd_async.tango.core import tango_command, CommandProxyReadCharacter
from ophyd_async.tango.testing import ExampleStrEnum, OneOfEverythingTangoDevice
from ophyd_async.core import NotConnectedError

@pytest.fixture(scope="module")
def everything_device_trl(subprocess_helper):
    with subprocess_helper(
        [{"class": OneOfEverythingTangoDevice, "devices": [{"name": "test/device/1"}]}]
    ) as context:
        trl = context.trls["test/device/1"]
        # Fix TRL if it contains '#' by ensuring it follows expected format
        if "#" in trl:
            from ophyd_async.tango.core import get_device_trl_and_attr
            # If get_device_trl_and_attr can't handle it, we might need a better fix
            pass
        yield trl

async def test_tango_command_scalar_echo(everything_device_trl):
    # OneOfEverythingTangoDevice has a {name}_cmd scalar command for many types
    # e.g. float64_cmd, int32_cmd, str_cmd
    from ophyd_async.tango.core import get_full_attr_trl
    trl = get_full_attr_trl(everything_device_trl, "float64_cmd")
    cmd = tango_command(trl)
    await cmd.connect()
    
    val = 3.14
    status = cmd(val)
    await status
    assert status.task.result() == val

async def test_tango_command_spectrum_echo(everything_device_trl):
    from ophyd_async.tango.core import get_full_attr_trl
    trl = get_full_attr_trl(everything_device_trl, "float64_spectrum_cmd")
    cmd = tango_command(trl)
    await cmd.connect()
    
    val = np.array([1.1, 2.2, 3.3], dtype=np.float64)
    status = cmd(val)
    await status
    assert np.array_equal(status.task.result(), val)

async def test_tango_command_enum(everything_device_trl):
    from ophyd_async.tango.core import get_full_attr_trl
    trl = get_full_attr_trl(everything_device_trl, "strenum_cmd")
    # strenum is DevEnum, it needs datatype to work correctly with ophyd-async StrictEnum
    cmd = tango_command(trl, datatype=ExampleStrEnum)
    await cmd.connect()
    
    val = ExampleStrEnum.B
    status = cmd(val)
    await status
    assert status.task.result() == val

async def test_tango_command_no_args(everything_device_trl):
    # reset_values is a @command with no args (DevVoid in/out)
    from ophyd_async.tango.core import get_full_attr_trl
    trl = get_full_attr_trl(everything_device_trl, "reset_values")
    cmd = tango_command(trl)
    await cmd.connect()
    
    status = cmd()
    await status
    assert status.task.result() is None

async def test_tango_command_too_many_args(everything_device_trl):
    from ophyd_async.tango.core import get_full_attr_trl
    trl = get_full_attr_trl(everything_device_trl, "float64_cmd")
    cmd = tango_command(trl)
    await cmd.connect()
    
    with pytest.raises(TypeError, match="expected 0 or 1 positional argument, got 2"):
        await cmd(1.0, 2.0)

async def test_tango_command_kwargs_rejected(everything_device_trl):
    from ophyd_async.tango.core import get_full_attr_trl
    trl = get_full_attr_trl(everything_device_trl, "float64_cmd")
    cmd = tango_command(trl)
    await cmd.connect()
    
    with pytest.raises(TypeError, match="Tango commands do not support keyword arguments"):
        await cmd(val=1.0)

async def test_tango_command_not_connected():
    cmd = tango_command("sys/tg_test/1/DevDouble")
    # Not calling connect()
    with pytest.raises(NotConnectedError, match="Not connected to sys/tg_test/1/DevDouble"):
        await cmd(1.0)

async def test_tango_command_invalid_trl(everything_device_trl):
    # Points to an attribute instead of a command
    from ophyd_async.tango.core import get_full_attr_trl
    trl = get_full_attr_trl(everything_device_trl, "float64")
    cmd = tango_command(trl)
    with pytest.raises(NotConnectedError, match="is not a Tango Command"):
        await cmd.connect()
