import asyncio
import os
from collections import defaultdict
from unittest.mock import ANY, Mock, call

import numpy as np
import pytest
from bluesky import plans as bp
from bluesky.protocols import Reading
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    LazyMock,
    NotConnected,
    init_devices,
)
from ophyd_async.epics import demo
from ophyd_async.testing import (
    StatusWatcher,
    assert_configuration,
    assert_emitted,
    assert_reading,
    assert_value,
    get_mock,
    get_mock_put,
    set_mock_value,
    wait_for_pending_wakeups,
)

# Can be removed once numpy >=2 is pinned.
scalar_int_dtype = (
    "<i4" if os.name == "nt" and np.version.version.startswith("1.") else "<i8"
)


@pytest.fixture
async def mock_motor():
    async with init_devices(mock=True):
        mock_motor = demo.DemoMotor("BLxxI-MO-TABLE-01:X:")
    set_mock_value(mock_motor.units, "mm")
    set_mock_value(mock_motor.precision, 3)
    set_mock_value(mock_motor.velocity, 1)
    yield mock_motor


@pytest.fixture
async def mock_point_detector():
    async with init_devices(mock=True):
        mock_point_detector = demo.DemoPointDetector("MOCK:DET:")
    yield mock_point_detector


async def test_motor_stopped(mock_motor: demo.DemoMotor):
    # Check it hasn't already been called
    stop_mock = get_mock_put(mock_motor.stop_)
    stop_mock.assert_not_called()
    # Call stop and check it's called with the default value
    await mock_motor.stop()
    stop_mock.assert_called_once_with(None, wait=True)
    # We can also track all the mock puts that have happened on the device
    parent_mock = get_mock(mock_motor)
    await mock_motor.velocity.set(15)
    assert parent_mock.mock_calls == [
        call.stop_.put(None, wait=True),
        call.velocity.put(15, wait=True),
    ]


async def test_motor_moving_well(mock_motor: demo.DemoMotor) -> None:
    # Start it moving
    s = mock_motor.set(0.55)
    # Watch for updates, and make sure the first update is the current position
    watcher = StatusWatcher(s)
    await watcher.wait_for_call(
        name="mock_motor",
        current=0.0,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.0, abs=0.08),
    )
    await assert_value(mock_motor.setpoint, 0.55)
    assert not s.done
    # Wait a bit and give it an update, checking that the watcher is called with it
    await asyncio.sleep(0.1)
    set_mock_value(mock_motor.readback, 0.1)
    await watcher.wait_for_call(
        name="mock_motor",
        current=0.1,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.1, abs=0.08),
    )
    # Make it almost get there and check that it completes
    set_mock_value(mock_motor.readback, 0.5499999)
    await wait_for_pending_wakeups()
    assert s.done
    assert s.success


async def test_retrieve_mock_and_assert(mock_motor: demo.DemoMotor):
    motor_setpoint_mock = get_mock_put(mock_motor.setpoint)
    await mock_motor.setpoint.set(10)
    motor_setpoint_mock.assert_called_once_with(10, wait=ANY)

    # Assert that velocity is set before move
    motor_velocity_mock = get_mock_put(mock_motor.velocity)

    parent_mock = Mock()
    parent_mock.attach_mock(motor_setpoint_mock, "setpoint")
    parent_mock.attach_mock(motor_velocity_mock, "velocity")

    await mock_motor.velocity.set(100)
    await mock_motor.setpoint.set(67)
    assert parent_mock.mock_calls == [
        call.velocity(100, wait=True),
        call.setpoint(67, wait=True),
    ]


async def test_mocks_in_device_share_parent():
    lm = LazyMock()
    mock_motor = demo.DemoMotor("BLxxI-MO-TABLE-01:Y:")
    await mock_motor.connect(mock=lm)
    mock = lm()

    assert get_mock(mock_motor) is mock
    assert get_mock(mock_motor.setpoint) is mock.setpoint
    assert get_mock_put(mock_motor.setpoint) is mock.setpoint.put
    await mock_motor.setpoint.set(10)
    get_mock_put(mock_motor.setpoint).assert_called_once_with(10, wait=ANY)

    await mock_motor.velocity.set(100)
    await mock_motor.setpoint.set(67)

    mock.reset_mock()
    await mock_motor.velocity.set(100)
    await mock_motor.setpoint.set(67)
    assert mock.mock_calls == [
        call.velocity.put(100, wait=True),
        call.setpoint.put(67, wait=True),
    ]


async def test_read_motor(mock_motor: demo.DemoMotor):
    await mock_motor.stage()
    await assert_reading(
        mock_motor,
        {"mock_motor": {"value": 0.0, "timestamp": ANY, "alarm_severity": 0}},
    )
    await assert_configuration(
        mock_motor,
        {
            "mock_motor-units": {
                "value": "mm",
                "timestamp": ANY,
                "alarm_severity": 0,
            },
            "mock_motor-velocity": {
                "value": 1.0,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
        },
    )
    # Check that changing the readback value changes the reading
    set_mock_value(mock_motor.readback, 0.5)
    await assert_value(mock_motor.readback, 0.5)
    await assert_reading(
        mock_motor,
        {"mock_motor": {"value": 0.5, "timestamp": ANY, "alarm_severity": 0}},
    )
    # Check we can still read when not staged
    await mock_motor.unstage()
    set_mock_value(mock_motor.readback, 0.1)
    await assert_reading(
        mock_motor,
        {"mock_motor": {"value": 0.1, "timestamp": ANY, "alarm_severity": 0}},
    )


async def test_set_velocity(mock_motor: demo.DemoMotor) -> None:
    v = mock_motor.velocity
    q: asyncio.Queue[dict[str, Reading]] = asyncio.Queue()
    v.subscribe(q.put_nowait)
    assert (await q.get())["mock_motor-velocity"]["value"] == 1.0
    await v.set(2.0)
    assert (await q.get())["mock_motor-velocity"]["value"] == 2.0
    v.clear_sub(q.put_nowait)
    await v.set(3.0)
    assert (await v.read())["mock_motor-velocity"]["value"] == 3.0
    assert q.empty()


async def test_zero_velocity(mock_motor: demo.DemoMotor) -> None:
    # v = sim_motor.velocity
    await mock_motor.velocity.set(0)
    with pytest.raises(ZeroDivisionError):
        await mock_motor.set(3.14)


async def test_mover_disconnected():
    with pytest.raises(NotConnected):
        async with init_devices(timeout=0.1):
            m = demo.DemoMotor("ca://PRE:", name="motor")
    assert m.name == "motor"


async def test_read_point_detector(mock_point_detector: demo.DemoPointDetector):
    channel = mock_point_detector.channel[1]
    assert (await channel.read())["mock_point_detector-channel-1-value"]["value"] == 0
    assert (await channel.read_configuration())["mock_point_detector-channel-1-mode"][
        "value"
    ] == demo.EnergyMode.LOW
    desc = (await channel.describe_configuration())[
        "mock_point_detector-channel-1-mode"
    ]
    assert desc["dtype"] == "string"
    assert desc["choices"] == ["Low Energy", "High Energy"]
    set_mock_value(channel.mode, demo.EnergyMode.HIGH)
    assert (await channel.read_configuration())["mock_point_detector-channel-1-mode"][
        "value"
    ] == demo.EnergyMode.HIGH


async def test_point_detector_in_plan(
    RE: RunEngine, mock_point_detector: demo.DemoPointDetector
):
    # Subscribe to new documents produce, putting them in a dict by type
    docs = defaultdict(list)
    RE.subscribe(lambda name, doc: docs[name].append(doc))
    # Set the channel values to a known value
    for i, channel in mock_point_detector.channel.items():
        set_mock_value(channel.value, 100 + i)
    # Run the plan and assert the right docs are produced
    RE(bp.count([mock_point_detector], num=2))
    assert_emitted(docs, start=1, descriptor=1, event=2, stop=1)
    assert docs["event"][1]["data"] == {
        "mock_point_detector-channel-1-value": 101,
        "mock_point_detector-channel-2-value": 102,
        "mock_point_detector-channel-3-value": 103,
    }


async def test_assembly_renaming() -> None:
    thing = demo.DemoStage("PRE")
    await thing.connect(mock=True)
    assert thing.x.name == ""
    assert thing.x.velocity.name == ""
    assert thing.x.stop_.name == ""
    await thing.x.velocity.set(456)
    assert await thing.x.velocity.get_value() == 456
    thing.set_name("foo")
    assert thing.x.name == "foo-x"
    assert thing.x.velocity.name == "foo-x-velocity"
    assert thing.x.stop_.name == "foo-x-stop_"


async def test_point_detector_disconnected():
    with pytest.raises(NotConnected) as e:
        async with init_devices(timeout=0.1):
            det = demo.DemoPointDetector("MOCK:DET:")
    expected = """
det: NotConnected:
    channel: NotConnected:
        1: NotConnected:
            value: NotConnected: ca://MOCK:DET:1:Value
            mode: NotConnected: ca://MOCK:DET:1:Mode
        2: NotConnected:
            value: NotConnected: ca://MOCK:DET:2:Value
            mode: NotConnected: ca://MOCK:DET:2:Mode
        3: NotConnected:
            value: NotConnected: ca://MOCK:DET:3:Value
            mode: NotConnected: ca://MOCK:DET:3:Mode
    acquire_time: NotConnected: ca://MOCK:DET:AcquireTime
    start: NotConnected: ca://MOCK:DET:Start.PROC
    acquiring: NotConnected: ca://MOCK:DET:Acquiring
    reset: NotConnected: ca://MOCK:DET:Reset.PROC
"""
    assert str(e.value) == expected

    assert det.name == "det"


async def test_point_detector_read_and_describe(
    mock_point_detector: demo.DemoPointDetector,
):
    set_mock_value(mock_point_detector.channel[1].value, 1)
    set_mock_value(mock_point_detector.channel[2].value, 5)
    set_mock_value(mock_point_detector.channel[3].value, 10)

    await mock_point_detector.stage()
    description = await mock_point_detector.describe()

    await mock_point_detector.unstage()
    await assert_reading(
        mock_point_detector,
        {
            "mock_point_detector-channel-1-value": {
                "value": 1,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
            "mock_point_detector-channel-2-value": {
                "value": 5,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
            "mock_point_detector-channel-3-value": {
                "value": 10,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
        },
    )
    assert description == {
        "mock_point_detector-channel-1-value": {
            "dtype": "integer",
            "dtype_numpy": scalar_int_dtype,
            "shape": [],
            "source": "mock+ca://MOCK:DET:1:Value",
        },
        "mock_point_detector-channel-2-value": {
            "dtype": "integer",
            "dtype_numpy": scalar_int_dtype,
            "shape": [],
            "source": "mock+ca://MOCK:DET:2:Value",
        },
        "mock_point_detector-channel-3-value": {
            "dtype": "integer",
            "dtype_numpy": scalar_int_dtype,
            "shape": [],
            "source": "mock+ca://MOCK:DET:3:Value",
        },
    }
