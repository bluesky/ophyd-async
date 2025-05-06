import asyncio
import math
import re
from unittest.mock import ANY, call

import pytest
from bluesky import RunEngine
from bluesky.plan_stubs import mv
from bluesky.protocols import Reading

from ophyd_async.core import (
    DerivedSignalFactory,
    StandardReadable,
    StaticFilenameProvider,
    StaticPathProvider,
    soft_signal_rw,
)
from ophyd_async.epics.meca500 import CartesianSpace, Meca500
from ophyd_async.sim import (
    HorizontalMirror,
    HorizontalMirrorDerived,
    TwoJackDerived,
    TwoJackTransform,
    VerticalMirror,
)
from ophyd_async.testing import (
    approx_value,
    assert_describe_signal,
    assert_reading,
    assert_value,
    get_mock,
)


@pytest.mark.parametrize(
    "x1, x2, x, roll",
    [
        (0, 0, 0, 0),
        (0, 1, 0.5, math.pi / 4),
        (2, 1, 1.5, -math.pi / 4),
    ],
)
async def test_get_returns_right_position(x1: float, x2: float, x: float, roll: float):
    inst = HorizontalMirror("mirror")
    await inst.x1.set(x1)
    await inst.x2.set(x2)
    assert inst.x.name == "mirror-x"
    assert inst.roll.name == "mirror-roll"
    for sig, value in [(inst.x, x), (inst.roll, roll)]:
        await assert_value(sig, value)
        await assert_reading(sig, {sig.name: {"value": value}})
        await assert_describe_signal(sig, dtype="number", dtype_numpy="<f8", shape=[])
        location = await sig.locate()
        assert location == {"setpoint": value, "readback": value}


async def assert_mirror_readings(
    results: asyncio.Queue[dict[str, Reading[float]]], x: float, roll: float
):
    for name, value in [("mirror-x", x), ("mirror-roll", roll)]:
        reading = await results.get()
        assert reading == {
            name: {"value": value, "timestamp": ANY, "alarm_severity": 0}
        }
    assert results.empty()


async def test_monitoring_position():
    results = asyncio.Queue[dict[str, Reading[float]]]()
    inst = HorizontalMirror("mirror")
    inst.x.subscribe(results.put_nowait)
    inst.roll.subscribe(results.put_nowait)
    await assert_mirror_readings(results, 0, 0)
    await inst.x2.set(1)
    await assert_mirror_readings(results, 0.5, math.pi / 4)
    inst.x.clear_sub(results.put_nowait)
    inst.roll.clear_sub(results.put_nowait)
    await inst.x1.set(1)
    assert results.empty()


async def test_setting_position_straight_through():
    inst = VerticalMirror("mirror")
    # Connect in mock mode so we can see what would have been set
    await inst.connect(mock=True)
    m = get_mock(inst)
    await inst.set(TwoJackDerived(height=1.5, angle=-math.pi / 4))
    assert m.mock_calls == [
        call.y1.user_setpoint.put(2.0, wait=True),
        call.y2.user_setpoint.put(1.0, wait=True),
    ]
    m.reset_mock()
    # Try to move just one axis
    await inst.height.set(0.5)
    assert m.mock_calls == [
        call.height.put(0.5, wait=True),
        call.y1.user_setpoint.put(1.0, wait=True),
        call.y2.user_setpoint.put(pytest.approx(0.0), wait=True),
    ]

    test = await inst.height.get_value()

    m.reset_mock()


async def test_setting_position_extra_indirection():
    inst = HorizontalMirror("mirror")
    # Connect in mock mode so we can see what would have been set
    await inst.connect(mock=True)
    m = get_mock(inst)
    await inst.set(HorizontalMirrorDerived(x=1.5, roll=-math.pi / 4))
    assert m.mock_calls == [
        call.x1.user_setpoint.put(2.0, wait=True),
        call.x2.user_setpoint.put(1.0, wait=True),
    ]
    m.reset_mock()
    # Try to move just one axis
    await inst.x.set(0.5)
    assert m.mock_calls == [
        call.x.put(0.5, wait=True),
        call.x1.user_setpoint.put(1.0, wait=True),
        call.x2.user_setpoint.put(pytest.approx(0.0), wait=True),
    ]
    m.reset_mock()


def test_mismatching_args():
    with pytest.raises(
        TypeError,
        match=re.escape(
            "Expected devices to be passed as keyword arguments"
            " {'distance': <class 'float'>, 'jack1': <class 'float'>, "
            "'jack2': <class 'float'>}, "
            "got {'jack1': <class 'float'>, 'jack22': <class 'float'>, "
            "'distance': <class 'float'>}"
        ),
    ):
        DerivedSignalFactory(
            TwoJackTransform,
            jack1=soft_signal_rw(float),
            jack22=soft_signal_rw(float),
            distance=soft_signal_rw(float),
        )


async def test_meca500_derived_signals():
    robot = Meca500("")
    await robot.connect(mock=True)
    await robot.set(CartesianSpace(x=0.0, y=0, z=0.308, alpha=180, beta=90, gamma=0))

    # Move x to achieve robot's zero position (i.e., all joints are 0°)
    await robot.x.set(0.190)

    # Read joint positions
    joint_values = await robot.read()

    # Check that all joints are approximately 0°
    for reading in joint_values.values():
        assert pytest.approx(reading["value"], abs=1e-4) == 0

    # Check that setting joint angle correctly recalculates derived axes
    await robot.joints[0].set(90)
    assert pytest.approx(await robot.y.get_value(), abs=1e-4) == 0.190
    assert pytest.approx(await robot.x.get_value(), abs=1e-4) == 0
