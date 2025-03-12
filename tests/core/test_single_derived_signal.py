import asyncio
from unittest.mock import call

import pytest

from ophyd_async.core import (
    AsyncStatus,
    Device,
    StrictEnum,
    derived_signal_r,
    derived_signal_rw,
    soft_signal_rw,
)
from ophyd_async.testing import (
    assert_describe_signal,
    assert_reading,
    assert_value,
    get_mock,
)


class BeamstopPosition(StrictEnum):
    IN_POSITION = "In position"
    OUT_OF_POSITION = "Out of position"


class Beamstop(Device):
    def __init__(self, name=""):
        # Raw signals
        self.x = soft_signal_rw(float)
        self.y = soft_signal_rw(float)
        # Derived signals
        self.position = derived_signal_r(self._get_position, x=self.x, y=self.y)
        super().__init__(name=name)

    def _get_position(self, x: float, y: float) -> BeamstopPosition:
        if abs(x) < 1 and abs(y) < 2:
            return BeamstopPosition.IN_POSITION
        else:
            return BeamstopPosition.OUT_OF_POSITION


class Positioner(Device):
    def __init__(self, name=""):
        # Raw signals
        self.x = soft_signal_rw(float)
        self.y = soft_signal_rw(float)
        # Derived signals
        self.position = derived_signal_rw(
            self._get_position, self.set, x=self.x, y=self.y
        )
        super().__init__(name=name)

    def _get_position(self, x: float, y: float) -> BeamstopPosition:
        if abs(x) < 1 and abs(y) < 2:
            return BeamstopPosition.IN_POSITION
        else:
            return BeamstopPosition.OUT_OF_POSITION

    @AsyncStatus.wrap
    async def set(self, value: BeamstopPosition, wait: bool) -> None:
        if value == BeamstopPosition.IN_POSITION:
            self.x.set(0, wait=wait)
            self.y.set(0, wait=wait)
        else:
            self.x.set(3, wait=wait)
            self.y.set(5, wait=wait)


@pytest.mark.parametrize(
    "x, y, position",
    [
        (0, 0, BeamstopPosition.IN_POSITION),
        (3, 5, BeamstopPosition.OUT_OF_POSITION),
    ],
)
@pytest.mark.parametrize("cls", [Beamstop, Positioner])
async def test_get_returns_right_position(
    cls: type[Beamstop | Positioner], x: float, y: float, position: BeamstopPosition
):
    inst = cls("inst")
    await inst.x.set(x)
    await inst.y.set(y)
    await assert_value(inst.position, position)
    await assert_reading(inst.position, {"inst-position": {"value": position}})
    await assert_describe_signal(
        inst.position,
        choices=[
            "In position",
            "Out of position",
        ],
        dtype="string",
        dtype_numpy="|S40",
        shape=[],
    )


@pytest.mark.parametrize("cls", [Beamstop, Positioner])
async def test_monitoring_position(cls: type[Beamstop | Positioner]):
    results = asyncio.Queue[BeamstopPosition]()
    inst = cls("inst")
    inst.position.subscribe_value(results.put_nowait)
    assert await results.get() == BeamstopPosition.IN_POSITION
    assert results.empty()
    await inst.x.set(3)
    assert await results.get() == BeamstopPosition.OUT_OF_POSITION
    assert results.empty()
    await inst.y.set(5)
    assert await results.get() == BeamstopPosition.OUT_OF_POSITION
    assert results.empty()
    await asyncio.gather(inst.x.set(0), inst.y.set(0))
    assert await results.get() == BeamstopPosition.OUT_OF_POSITION
    assert await results.get() == BeamstopPosition.IN_POSITION
    assert results.empty()


async def test_setting_position():
    inst = Positioner("inst")
    # Connect in mock mode so we can see what would have been set
    await inst.connect(mock=True)
    m = get_mock(inst)
    await inst.position.set(BeamstopPosition.OUT_OF_POSITION)
    assert m.mock_calls == [
        call.x.put(3, wait=True),
        call.y.put(5, wait=True),
    ]
    m.reset_mock()
    await inst.position.set(BeamstopPosition.IN_POSITION, wait=False)
    assert m.mock_calls == [
        call.x.put(0, wait=False),
        call.y.put(0, wait=False),
    ]
