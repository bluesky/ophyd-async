import asyncio
import re
from unittest.mock import MagicMock, call, patch

import pytest
from bluesky.protocols import Reading, Subscribable

from ophyd_async.core import (
    Callback,
    Signal,
    SignalBackend,
    SignalDatatype,
    derived_signal_r,
    derived_signal_rw,
    derived_signal_w,
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
    partial_reading,
)


@pytest.fixture
def movable_beamstop() -> MovableBeamstop:
    return MovableBeamstop("device")


@pytest.fixture
def readonly_beamstop() -> ReadOnlyBeamstop:
    return ReadOnlyBeamstop("device")


def _get_position(foo: float, bar: float) -> BeamstopPosition:
    if abs(foo) < 1 and abs(bar) < 2:
        return BeamstopPosition.IN_POSITION
    else:
        return BeamstopPosition.OUT_OF_POSITION


def _get_position_wrong_args(x: float, y: float) -> BeamstopPosition:
    if abs(x) < 1 and abs(y) < 2:
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
    await assert_reading(inst.position, {"inst-position": partial_reading(position)})
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
        inst, {f"exploder-signals-{i}": partial_reading(0) for i in range(1, 4)}
    )
    await inst.set_all.set(5)
    await assert_reading(
        inst, {f"exploder-signals-{i}": partial_reading(5) for i in range(1, 4)}
    )


@pytest.mark.parametrize(
    "func, expected_msg, args",
    [
        (
            _get_position_wrong_args,
            "Expected the following to be passed as keyword arguments "
            "{'x': <class 'float'>, 'y': <class 'float'>}, "
            "got {'foo': <class 'float'>, 'bar': <class 'float'>}",
            {"foo": soft_signal_rw(float), "bar": soft_signal_rw(float)},
        ),
        (
            _get_position,
            "Expected the following to be passed as keyword arguments "
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


def _get(ts: int) -> float:
    return ts


async def _put(value: float) -> None:
    pass


@pytest.fixture
def derived_signal_backend() -> SignalBackend[SignalDatatype]:
    signal_rw = soft_signal_rw(int, initial_value=4)
    derived = derived_signal_rw(_get, _put, ts=signal_rw)
    return derived._connector.backend


async def test_derived_signal_rw_works_with_signal_r():
    signal_r, _ = soft_signal_r_and_setter(int, initial_value=4)
    derived = derived_signal_rw(_get, _put, ts=signal_r)
    assert await derived.get_value() == 4


async def test_derived_signal_allows_literals():
    signal_rw = soft_signal_rw(int, 0, "TEST")

    def _add_const_to_value(signal: int, const: int) -> int:
        return const + signal

    signal_r = derived_signal_r(
        _add_const_to_value,
        signal=signal_rw,
        const=24,
    )
    assert await signal_r.get_value() == 24
    await signal_rw.set(10)
    assert await signal_r.get_value() == 34


async def test_validate_by_type(derived_signal_backend: SignalBackend):
    def float_get(ts: float) -> float:
        return ts

    with pytest.raises(TypeError, match=re.escape(" is not an instance of")):
        derived_signal_rw(float_get, _put, ts=Signal(derived_signal_backend))


async def test_set_derived_not_initialized():
    sig = derived_signal_r(_get, ts=soft_signal_rw(int, initial_value=4))
    with pytest.raises(
        RuntimeError,
        match="Cannot put as no set_derived method given",
    ):
        await sig._connector.backend.put(1.0, True)


async def test_derived_update_cached_reading_not_initialized(
    derived_signal_backend: SignalBackend,
):
    class test_cls(Subscribable):
        def subscribe(self, function: Callback) -> None:
            pass

        def clear_sub(self, function: Callback) -> None:
            function("")

        @property
        def name(self) -> str:
            return ""

    with patch.object(
        derived_signal_backend.transformer,  # type: ignore
        "raw_and_transform_subscribables",
        {"raw_device": test_cls()},
    ):
        with pytest.raises(
            RuntimeError,
            match=re.escape(
                "Cannot update cached reading as it has not been initialised"
            ),
        ):  # noqa: E501
            derived_signal_backend.set_callback(None)


async def test_set_derived_callback_already_set(derived_signal_backend: SignalBackend):
    mock_callback = MagicMock(Callback[Reading])
    derived_signal_backend.set_callback(mock_callback)
    with pytest.raises(RuntimeError, match=re.escape("Callback already set for")):
        derived_signal_backend.set_callback(mock_callback)


@patch("ophyd_async.core._derived_signal.get_type_hints", return_value={})
def test_get_return_datatype_no_type(movable_beamstop: MovableBeamstop):
    with pytest.raises(
        TypeError, match=re.escape("does not have a type hint for it's return value")
    ):
        derived_signal_r(movable_beamstop._get_position)


@patch("ophyd_async.core._derived_signal.get_type_hints", return_value={})
def test_get_first_arg_datatype_no_type(movable_beamstop: MovableBeamstop):
    with pytest.raises(
        TypeError, match=re.escape("does not have a type hinted argument")
    ):
        derived_signal_w(movable_beamstop._set_from_position)


def test_derived_signal_rw_type_error(movable_beamstop: MovableBeamstop):
    with patch.object(
        movable_beamstop, "_set_from_position", movable_beamstop._get_position
    ):  # noqa: E501
        with pytest.raises(TypeError):
            derived_signal_rw(
                movable_beamstop._get_position, movable_beamstop._set_from_position
            )  # noqa: E501
