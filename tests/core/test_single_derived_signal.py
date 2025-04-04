import asyncio
import re
from unittest.mock import call, patch

import pytest
from bluesky.protocols import Reading

from ophyd_async.core import (
    derived_signal_r,
    soft_signal_rw,
)
from ophyd_async.core._derived_signal import (
    _get_first_arg_datatype,  # noqa: PLC2701
    _get_return_datatype,  # noqa: PLC2701
    derived_signal_rw,  # noqa: PLC2701
)
from ophyd_async.core._derived_signal_backend import (
    SignalTransformer,  # noqa: PLC2701
    Transform,  # noqa: PLC2701
    validate_by_type,  # noqa: PLC2701
)
from ophyd_async.core._signal import SignalR  # noqa: PLC2701
from ophyd_async.core._utils import StrictEnumMeta  # noqa: PLC2701
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


@pytest.fixture
def movable_beamstop() -> MovableBeamstop:
    return MovableBeamstop("device")


@pytest.fixture
def readonly_beamstop() -> ReadOnlyBeamstop:
    return ReadOnlyBeamstop("device")


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


async def test_setting_position(movable_beamstop: MovableBeamstop):
    # Connect in mock mode so we can see what would have been set
    await movable_beamstop.connect(mock=True)
    m = get_mock(movable_beamstop)
    await movable_beamstop.position.set(BeamstopPosition.OUT_OF_POSITION)
    assert m.mock_calls == [
        call.position.put(BeamstopPosition.OUT_OF_POSITION, wait=True),
        call.x.put(3, wait=True),
        call.y.put(5, wait=True),
    ]
    m.reset_mock()
    await movable_beamstop.position.set(BeamstopPosition.IN_POSITION)
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


@patch("ophyd_async.core._derived_signal_backend.TYPE_CHECKING", True)
def test_validate_by_type(
    movable_beamstop: MovableBeamstop,
    readonly_beamstop: ReadOnlyBeamstop
) -> None:
    invalid_devices_dict = {device.name: device for device in [movable_beamstop,
                                                               readonly_beamstop]}
    with pytest.raises(TypeError):
        validate_by_type(invalid_devices_dict, MovableBeamstop)
    with pytest.raises(TypeError):
        validate_by_type({movable_beamstop.name: movable_beamstop}, ReadOnlyBeamstop)
    valid_devices_dict = {device.name: device for device in [movable_beamstop,
                                                             MovableBeamstop("mvb2")]}
    assert validate_by_type(valid_devices_dict, MovableBeamstop) == valid_devices_dict


@pytest.fixture
def null_transformer() -> SignalTransformer:
    return SignalTransformer(Transform, None, None)


@pytest.fixture
def new_readings() -> dict[str, Reading]:
    return {"device-position": Reading(value=0.0, timestamp=0.0)}


async def test_set_derived_not_initialized(null_transformer: SignalTransformer):
    with pytest.raises(RuntimeError):
        await null_transformer.set_derived("name", None)


async def test_get_transform_cached(
    null_transformer: SignalTransformer,
    new_readings: dict[str, Reading]
) -> None:
    with patch.object(null_transformer, '_cached_readings', new_readings):
        with patch.object(null_transformer, 'raw_and_transform_subscribables', {"device": SignalR}):  # noqa: E501
            assert null_transformer._cached_readings == new_readings
            r = await null_transformer.get_transform()
            assert isinstance(r, Transform)


def test_update_cached_reading_non_initialized(
    null_transformer: SignalTransformer,
    new_readings: dict[str, Reading]
) -> None:
    with pytest.raises(RuntimeError):
        null_transformer._update_cached_reading(new_readings)


def test_update_cached_reading_initialized(
    null_transformer: SignalTransformer,
    new_readings: dict[str, Reading]
) -> None:
    null_transformer._cached_readings = {}
    null_transformer._update_cached_reading(new_readings)
    assert null_transformer._cached_readings == new_readings


@patch("ophyd_async.core._utils.Callback")
def test_set_callback_already_set(
    mock_class,
    null_transformer: SignalTransformer
) -> None:
    device_name = "device"
    with patch.object(null_transformer, '_derived_callbacks', {device_name: mock_class}):  # noqa: E501
        with pytest.raises(
            RuntimeError,
            match=re.escape(f"Callback already set for {device_name}")
            ):
            null_transformer.set_callback(device_name, mock_class)


@patch("ophyd_async.core._derived_signal.get_type_hints", return_value={})
def test_get_return_datatype_no_type(movable_beamstop: MovableBeamstop):
    with pytest.raises(
        TypeError,
        match=re.escape("does not have a type hint for it's return value")
        ):
        _get_return_datatype(movable_beamstop._get_position)


def test_get_return_datatype(movable_beamstop: MovableBeamstop):
    result = _get_return_datatype(movable_beamstop._get_position)
    assert isinstance(result, StrictEnumMeta)


@patch("ophyd_async.core._derived_signal.get_type_hints", return_value={})
def test_get_first_arg_datatype_no_type(movable_beamstop: MovableBeamstop):
    with pytest.raises(
        TypeError,
        match=re.escape("does not have a type hinted argument")
        ):
        _get_first_arg_datatype(movable_beamstop._set_from_position)


def test_derived_signal_rw_type_error(movable_beamstop: MovableBeamstop):
    with patch.object(movable_beamstop, '_set_from_position', movable_beamstop._get_position):  # noqa: E501
        with pytest.raises(TypeError):
            derived_signal_rw(movable_beamstop._get_position, movable_beamstop._set_from_position)  # noqa: E501
