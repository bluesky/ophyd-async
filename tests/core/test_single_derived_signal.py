import asyncio
import re
from unittest.mock import call

import pytest

from ophyd_async.core import (
    derived_signal_r,
    derived_signal_rw,
    soft_signal_r_and_setter,
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


def _get_position(foo: float, bar: float) -> BeamstopPosition:
    if abs(foo) < 1 and abs(bar) < 2:
        return BeamstopPosition.IN_POSITION
    else:
        return BeamstopPosition.OUT_OF_POSITION


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


@pytest.mark.parametrize(
    "func, expected_msg, args",
    [
        (
            _get_position,
            "Expected devices to be passed as keyword arguments "
            "{'foo': <class 'float'>, 'bar': <class 'float'>}, "
            "got {'x': <class 'float'>, 'y': <class 'float'>}",
            {"x": soft_signal_rw(float), "y": soft_signal_rw(float)},
        ),
        (
            _get_position,
            "Expected devices to be passed as keyword arguments "
            "{'foo': <class 'float'>, 'bar': <class 'float'>}, "
            "got {'foo': <class 'int'>, 'bar': <class 'int'>}",
            {
                "foo": soft_signal_rw(int),
                "bar": soft_signal_rw(int),
            },  # Signals are of wrong type.
        ),
    ],
)
def test_mismatching_args_and_types(func, expected_msg, args):
    with pytest.raises(TypeError, match=re.escape(expected_msg)):
        derived_signal_r(func, **args)


async def test_derived_signal_rw_works_with_signal_r():
    signal_r, _ = soft_signal_r_and_setter(int, initial_value=4)

    def _get(ts: int) -> float:
        return ts

    async def _put(value: float) -> None:
        pass

    derived = derived_signal_rw(_get, _put, ts=signal_r)
    assert await derived.get_value() == 4
