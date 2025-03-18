import asyncio
from typing import Generic, TypedDict, TypeVar, cast
from unittest.mock import ANY, call

import numpy as np
import pytest
from bluesky.protocols import Reading

from ophyd_async.core import (
    Array1D,
    AsyncStatus,
    DerivedSignalCreator,
    Device,
    DTypeScalar_co,
    Transform,
    soft_signal_rw,
)
from ophyd_async.sim import SimMotor
from ophyd_async.testing import (
    assert_describe_signal,
    assert_reading,
    assert_value,
    get_mock,
)

F = TypeVar("F", float, Array1D[np.float64])


def convert_to_type_of(arr: Array1D[DTypeScalar_co], *need_types: F) -> F:
    types = {type(need_type) for need_type in need_types}
    if len(types) != 1:
        msg = f"All need_types must be the same type, got {types}"
        raise ValueError(msg)
    return cast(F, arr if types.pop() == np.ndarray else float(arr))


class TwoJackRaw(TypedDict, Generic[F]):
    jack1: F
    jack2: F


class TwoJackDerived(TypedDict, Generic[F]):
    height: F
    angle: F


class TwoJackTransform(Transform):
    distance: float

    def raw_to_derived(self, *, jack1: F, jack2: F) -> TwoJackDerived[F]:
        diff = jack2 - jack1
        return TwoJackDerived(
            height=jack1 + diff / 2,
            # need the case as returns numpy float rather than float64, but this
            # is ok at runtime
            angle=convert_to_type_of(np.atan(diff / self.distance), jack1),
        )

    def derived_to_raw(self, *, height: F, angle: F) -> TwoJackRaw[F]:
        diff = convert_to_type_of(np.tan(angle) * self.distance, height)
        return TwoJackRaw(
            jack1=height - diff / 2,
            jack2=height + diff / 2,
        )


class MirrorDerived(TypedDict):
    x: float
    roll: float


class Mirror(Device):
    def __init__(self, name=""):
        # Raw signals
        self.x1 = SimMotor()
        self.x2 = SimMotor()
        # Parameter
        self.x1_x2_distance = soft_signal_rw(float, initial_value=1)
        # Derived signals
        self._creator = DerivedSignalCreator(
            TwoJackTransform,
            self.set,
            jack1=self.x1,
            jack2=self.x2,
            distance=self.x1_x2_distance,
        )
        self.x = self._creator.derived_signal_rw(float, "height", "x")
        self.roll = self._creator.derived_signal_rw(float, "angle", "roll")
        super().__init__(name=name)

    @AsyncStatus.wrap
    async def set(self, derived: MirrorDerived) -> None:
        transform = await self._creator.get_transform()
        raw = transform.derived_to_raw(height=derived["x"], angle=derived["roll"])
        await asyncio.gather(
            self.x1.set(raw["jack1"]),
            self.x2.set(raw["jack2"]),
        )


@pytest.mark.parametrize(
    "x1, x2, x, roll",
    [
        (0, 0, 0, 0),
        (0, 1, 0.5, np.pi / 4),
        (2, 1, 1.5, -np.pi / 4),
    ],
)
async def test_get_returns_right_position(x1: float, x2: float, x: float, roll: float):
    inst = Mirror("mirror")
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
    inst = Mirror("mirror")
    inst.x.subscribe(results.put_nowait)
    inst.roll.subscribe(results.put_nowait)
    await assert_mirror_readings(results, 0, 0)
    await inst.x2.set(1)
    await assert_mirror_readings(results, 0.5, np.pi / 4)


async def test_setting_position():
    inst = Mirror("mirror")
    # Connect in mock mode so we can see what would have been set
    await inst.connect(mock=True)
    m = get_mock(inst)
    await inst.set(MirrorDerived(x=1.5, roll=-np.pi / 4))
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
