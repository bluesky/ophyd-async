import asyncio
import re
from unittest.mock import call

import pytest

from ophyd_async.core import (
    derived_signal_r,
    soft_signal_rw,
)
from ophyd_async.testing import (
    BeamstopPosition,
    Exploder,
    MovableBeamstop,
    ReadOnlyBeamstop,
    assert_describe_signal,
    assert_reading,
    assert_value,
    get_mock,
)


@pytest.mark.parametrize(
    "x, y, position",
    [
        (0, 0, BeamstopPosition.IN_POSITION),
        (3, 5, BeamstopPosition.OUT_OF_POSITION),
    ],
)
@pytest.mark.parametrize("cls", [ReadOnlyBeamstop, MovableBeamstop])
async def test_get_returns_right_position(
    cls: type[ReadOnlyBeamstop | MovableBeamstop],
    x: float,
    y: float,
    position: BeamstopPosition,
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


@pytest.mark.parametrize("cls", [ReadOnlyBeamstop, MovableBeamstop])
async def test_monitoring_position(cls: type[ReadOnlyBeamstop | MovableBeamstop]):
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
    inst = MovableBeamstop("inst")
    # Connect in mock mode so we can see what would have been set
    await inst.connect(mock=True)
    m = get_mock(inst)
    await inst.position.set(BeamstopPosition.OUT_OF_POSITION)
    assert m.mock_calls == [
        call.position.put(BeamstopPosition.OUT_OF_POSITION, wait=True),
        call.x.put(3, wait=True),
        call.y.put(5, wait=True),
    ]
    m.reset_mock()
    await inst.position.set(BeamstopPosition.IN_POSITION)
    assert m.mock_calls == [
        call.position.put(BeamstopPosition.IN_POSITION, wait=True),
        call.x.put(0, wait=True),
        call.y.put(0, wait=True),
    ]


async def test_setting_all():
    inst = Exploder(3, "exploder")
    await assert_reading(
        inst, {f"exploder-signals-{i}": {"value": 0} for i in range(1, 4)}
    )
    await inst.set_all.set(5)
    await assert_reading(
        inst, {f"exploder-signals-{i}": {"value": 5} for i in range(1, 4)}
    )


def test_mismatching_args():
    def _get_position(x: float, y: float) -> BeamstopPosition:
        if abs(x) < 1 and abs(y) < 2:
            return BeamstopPosition.IN_POSITION
        else:
            return BeamstopPosition.OUT_OF_POSITION

    with pytest.raises(
        TypeError,
        match=re.escape(
            "Expected devices to be passed as keyword arguments ['x', 'y'], "
            "got ['foo', 'bar']"
        ),
    ):
        derived_signal_r(
            _get_position, foo=soft_signal_rw(float), bar=soft_signal_rw(float)
        )
