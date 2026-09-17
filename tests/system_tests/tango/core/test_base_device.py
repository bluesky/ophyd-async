import asyncio
import time
from enum import Enum
from typing import Annotated as A
from typing import TypeVar

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import numpy as np
import pytest
import tango
from bluesky import RunEngine
from tango import (
    AttrDataFormat,
    AttrQuality,
    DevState,
)
from tango.asyncio import DeviceProxy as AsyncDeviceProxy

from ophyd_async.core import (
    Array1D,
    Command,
    Ignore,
    SignalRW,
    StandardReadable,
    init_devices,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.tango import demo, testing
from ophyd_async.tango.core import TangoDevice, get_full_attr_trl, get_python_type
from ophyd_async.tango.demo import (
    DemoMotor,
    DemoPointDetector,
    DemoPointDetectorChannel,
    DemoStage,
    EnergyMode,
)
from ophyd_async.testing import assert_reading, find_free_port

T = TypeVar("T")

# --------------------------------------------------------------------
#               fixtures to run Echo device
# --------------------------------------------------------------------

TESTED_FEATURES = ["array", "limitedvalue", "justvalue"]


# --------------------------------------------------------------------
class TestTangoReadable(TangoDevice, StandardReadable):
    __test__ = False
    justvalue: A[SignalRW[int], Format.HINTED_UNCACHED_SIGNAL]
    array: A[SignalRW[Array1D[np.float64]], Format.HINTED_UNCACHED_SIGNAL]
    limitedvalue: A[SignalRW[float], Format.HINTED_UNCACHED_SIGNAL]
    ignored_attr: Ignore


# --------------------------------------------------------------------
async def describe_class(fqtrl):
    description = {}
    values = {}
    dev = await AsyncDeviceProxy(fqtrl)

    for name in TESTED_FEATURES:
        dtype = "none"
        if name in dev.get_attribute_list():
            attr_conf = await dev.get_attribute_config(name)
            attr_value = await dev.read_attribute(name)
            value = attr_value.value
            py_type = get_python_type(attr_conf)

            if py_type is int:
                dtype = "integer"
            if py_type is float:
                dtype = "number"
            if py_type is str:
                dtype = "string"
            if py_type is bool:
                dtype = "boolean"

            max_x = attr_conf.max_dim_x
            max_y = attr_conf.max_dim_y
            if attr_conf.data_format == AttrDataFormat.SCALAR:
                shape = []
            elif attr_conf.data_format == AttrDataFormat.SPECTRUM:
                dtype = "array"
                shape = [max_x]
            else:
                dtype = "array"
                shape = [max_y, max_x]

        elif name in dev.get_command_list():
            cmd_conf = await dev.get_command_config(name)
            _, _, descr = get_python_type(cmd_conf)
            shape = []
            value = getattr(dev, name)()

        else:
            raise RuntimeError(
                f"Cannot find {name} in attributes/commands (pipes are not supported!)"
            )

        description[f"test_device-{name}"] = {
            "source": get_full_attr_trl(fqtrl, name),
            "dtype": dtype,
            "shape": shape,
        }

        values[f"test_device-{name}"] = {
            "value": value,
            "timestamp": pytest.approx(time.time()),
            "alarm_severity": AttrQuality.ATTR_VALID,
        }

    return values, description


# --------------------------------------------------------------------
def get_test_descriptor(python_type: type[T], value: T, is_cmd: bool) -> dict:
    if python_type in [bool, int]:
        return {"dtype": "integer", "shape": []}
    if python_type in [float]:
        return {"dtype": "number", "shape": []}
    if python_type in [str]:
        return {"dtype": "string", "shape": []}
    if issubclass(python_type, DevState):
        return {"dtype": "string", "shape": [], "choices": list(DevState.names.keys())}
    if issubclass(python_type, Enum):
        return {
            "dtype": "string",
            "shape": [],
            "choices": [] if is_cmd else [member.name for member in python_type],
        }

    return {
        "dtype": "array",
        "shape": [np.Inf] if is_cmd else list(np.array(value).shape),
    }


# --------------------------------------------------------------------
# tango_test_device and sim_test_context_trls fixtures come from conftest.py -
# every test module in this directory shares the one fixed device server catalog.
# --------------------------------------------------------------------


@pytest.mark.timeout(8.0)
@pytest.mark.asyncio
async def test_connect(tango_test_device):
    values, _ = await describe_class(tango_test_device)
    async with init_devices():
        test_device = TestTangoReadable(tango_test_device)

    assert test_device.name == "test_device"
    await assert_reading(test_device, values)


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_set_trl(tango_test_device):
    values, description = await describe_class(tango_test_device)
    test_device = TestTangoReadable(trl="", name="test_device")

    test_device._connector.set_trl(tango_test_device)
    await test_device.connect()

    assert test_device.name == "test_device"
    test_device_descriptor = await test_device.describe()
    for name, desc in description.items():
        assert test_device_descriptor[name]["source"] == desc["source"]
        assert test_device_descriptor[name]["dtype"] == desc["dtype"]
        assert test_device_descriptor[name]["shape"] == desc["shape"]

    await assert_reading(test_device, values)


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("use_trl", [True, False])
async def test_connect_proxy(tango_test_device, use_trl: str | None):
    if use_trl:
        test_device = TestTangoReadable(trl=tango_test_device)
        assert test_device.get_trl() == tango_test_device
        test_device._proxy = None
        await test_device.connect()
        assert isinstance(test_device.get_proxy(), tango._tango.DeviceProxy)
    else:
        test_device = TestTangoReadable()
        assert test_device


# --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_with_bluesky(tango_test_device):
    # now let's do some bluesky stuff
    RE = RunEngine()
    with init_devices():
        device = TestTangoReadable(tango_test_device)
    RE(bp.count([device]))


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.timeout(60.0)
async def test_tango_device_servers_launcher():
    """Smoke test `ophyd_async.tango.testing`/`ophyd_async.tango.demo`'s
    `DEVICE_SERVERS` as standalone launchers, independent of the shared
    conftest.py subprocesses - proves each is self-sufficient (predictable TRL,
    no readback needed, clean startup/shutdown) exactly as a user running one
    directly would rely on."""
    prefix = testing.generate_random_trl_prefix()
    testing_port = find_free_port()
    demo_port = find_free_port()
    testing_process = testing.start_tango_device_servers(
        testing.DEVICE_SERVERS, prefix, str(testing_port)
    )
    demo_process = testing.start_tango_device_servers(
        demo.DEVICE_SERVERS, prefix, str(demo_port), "3"
    )
    try:
        basic_proxy = await AsyncDeviceProxy(testing.trl(prefix, testing_port, "basic"))
        assert await basic_proxy.read_attribute("readback")
        motor_proxy = await AsyncDeviceProxy(testing.trl(prefix, demo_port, "motor-x"))
        assert await motor_proxy.read_attribute("readback")
    finally:
        demo_process.stop()
        testing_process.stop()


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.timeout(8.0)
async def test_tango_enum_roundtrip(sim_test_context_trls):
    channel = DemoPointDetectorChannel(
        name="channel",
        trl=sim_test_context_trls["channel-1"],
    )
    await channel.connect()

    # Write HIGH (index 1) and read it back
    await channel.mode.set(EnergyMode.HIGH)
    assert await channel.mode.get_value() == EnergyMode.HIGH

    # Write LOW (index 0) and read it back
    await channel.mode.set(EnergyMode.LOW)
    assert await channel.mode.get_value() == EnergyMode.LOW


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.timeout(8.0)
async def test_tango_stage(sim_test_context_trls):
    stage = DemoStage(
        name="stage",
        x_trl=sim_test_context_trls["motor-x"],
        y_trl=sim_test_context_trls["motor-y"],
    )
    await stage.connect()
    assert stage.x.name == "stage-x"
    assert stage.y.name == "stage-y"
    reading = await stage.read()
    assert "stage-x" in reading
    assert "stage-y" in reading


# --------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.timeout(15.5)
async def test_tango_sim(sim_test_context_trls):
    detector = DemoPointDetector(
        name="detector",
        trl=sim_test_context_trls["detector"],
        channel_trls=[
            sim_test_context_trls["channel-1"],
            sim_test_context_trls["channel-2"],
        ],
    )
    await detector.connect()
    await detector.acquire_time.set(0.1)
    await detector.trigger()
    await detector.acquiring.read()
    await detector.acquire_time.read()

    motor = DemoMotor(name="motor", trl=sim_test_context_trls["motor-x"])
    await motor.connect()
    await motor.velocity.set(0.5)

    RE = RunEngine()

    RE(bps.read(detector))
    RE(bps.mv(motor, 0))
    RE(bp.count(list(detector.channel.values())))

    set_status = motor.set(1.0)
    await asyncio.sleep(1.0)

    await motor.stop(success=True)
    await set_status
    assert set_status.done


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_fill_signals", [True, False])
@pytest.mark.timeout(8.8)
async def test_signal_autofill(tango_test_device, auto_fill_signals):
    test_device = TestTangoReadable(
        trl=tango_test_device, auto_fill_signals=auto_fill_signals
    )
    await test_device.connect()
    if auto_fill_signals:
        assert not hasattr(test_device, "ignored_attr")
        assert hasattr(test_device, "readback")
    else:
        assert not hasattr(test_device, "ignored_attr")
        assert not hasattr(test_device, "readback")


@pytest.mark.asyncio
@pytest.mark.timeout(10.0)
async def test_command_autofill(tango_test_device):
    test_device = TestTangoReadable(trl=tango_test_device)
    await test_device.connect()

    assert hasattr(test_device, "echo")
    echo = test_device.echo
    assert hasattr(test_device, "set_msg")
    set_msg = test_device.set_msg
    assert hasattr(test_device, "get_msg")
    get_msg = test_device.get_msg
    assert hasattr(test_device, "clear")
    clear = test_device.clear

    assert isinstance(echo, Command)
    assert isinstance(set_msg, Command)
    assert isinstance(get_msg, Command)
    assert isinstance(clear, Command)

    reply = await echo.execute("hello_world")
    assert reply == "hello_world"

    assert await get_msg.execute() == "Hello"
    await set_msg.execute("new message")
    assert await get_msg.execute() == "new message"

    assert await clear.execute() is None
