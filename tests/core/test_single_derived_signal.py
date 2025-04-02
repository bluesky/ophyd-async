import asyncio
import re
from unittest.mock import call
from unittest.mock import patch

import pytest

from ophyd_async.core import (
    derived_signal_r,
    soft_signal_rw,
)
from ophyd_async.core._derived_signal import DerivedSignalFactory, _get_first_arg_datatype, _get_return_datatype, _make_factory, derived_signal_rw
from ophyd_async.core._signal import SignalR, SignalRW
from ophyd_async.core._table import Table
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

from ophyd_async.core._derived_signal_backend import DerivedSignalBackend, SignalTransformer, Transform, validate_by_type
from ophyd_async.core._utils import StrictEnumMeta
from bluesky.protocols import Reading

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

@pytest.fixture
def movable_beamstop() -> MovableBeamstop:
    return  MovableBeamstop("device")

@pytest.fixture
def readonly_beamstop() -> ReadOnlyBeamstop:
    return  ReadOnlyBeamstop("device")

async def test_setting_position(movable_beamstop:MovableBeamstop):
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
    movable_beamstop:MovableBeamstop,
    readonly_beamstop: ReadOnlyBeamstop
) -> None:
    movable_beamstop2 = MovableBeamstop("mvb2")
    invalid_devices_dict = {device.name: device for device in [movable_beamstop, readonly_beamstop]}
    with pytest.raises(Exception) as e_info:
        validate_by_type(invalid_devices_dict, MovableBeamstop)
    assert type(e_info.value) == TypeError

    valid_devices_dict = {device.name: device for device in [movable_beamstop, movable_beamstop2]}
    assert validate_by_type(valid_devices_dict, MovableBeamstop) == valid_devices_dict

    with pytest.raises(Exception) as e_info:
        validate_by_type({movable_beamstop.name: movable_beamstop}, ReadOnlyBeamstop)
    assert type(e_info.value) == TypeError

@pytest.fixture
def transformer() -> SignalTransformer:
    return  SignalTransformer(Transform, None, None)

@pytest.fixture
def new_readings() -> dict[str, Reading]:
    return  {"device-position": Reading(value=0.0,timestamp=0.0)}

@pytest.fixture
def derived_signal_backend(transformer: SignalTransformer) -> DerivedSignalBackend:
    return DerivedSignalBackend(Table, "derived_backend", transformer)

async def test_set_derived_not_initialized(
    transformer : SignalTransformer
) -> None:
    with pytest.raises(Exception) as e_info:
        await transformer.set_derived("name",None)
    assert type(e_info.value) == RuntimeError

async def test_get_transform_cached(
    transformer : SignalTransformer,
    new_readings: dict[str, Reading]
) -> None:
    with patch.object(transformer, '_cached_readings', new_readings):
        with patch.object(transformer, 'raw_and_transform_subscribables', {"device":SignalR}):
            assert transformer._cached_readings == new_readings
            r = await transformer.get_transform()
            assert isinstance(r,Transform)

def test_update_cached_reading_non_initialized(
    transformer : SignalTransformer,
    new_readings: dict[str, Reading]
) -> None:
    with pytest.raises(Exception) as e_info:
        transformer._update_cached_reading(new_readings)
    assert type(e_info.value) == RuntimeError

def test_update_cached_reading_initialized(
    transformer : SignalTransformer,
    new_readings: dict[str, Reading]
) -> None:
    transformer._cached_readings = {}
    transformer._update_cached_reading(new_readings)
    assert transformer._cached_readings == new_readings

@patch("ophyd_async.core._utils.Callback")
def test_set_callback_already_set(
    mock_class,
    transformer : SignalTransformer
) -> None:
    device_name = "device"
    with patch.object(transformer, '_derived_callbacks', {device_name:mock_class}):
        with pytest.raises(Exception) as e_info:
            transformer.set_callback(device_name,mock_class)
        assert type(e_info.value) == RuntimeError

async def test_derived_signal_backend_connect_pass(
    derived_signal_backend:DerivedSignalBackend
) -> None:
    result = await derived_signal_backend.connect(0.0)
    assert result == None

def test_derived_signal_backend_set_value(
    derived_signal_backend:DerivedSignalBackend
) -> None:
    with pytest.raises(Exception) as e_info:
        derived_signal_backend.set_value(0.0)
    assert type(e_info.value) == RuntimeError

async def test_derived_signal_backend_put_fails(
    derived_signal_backend:DerivedSignalBackend
) -> None:
    with pytest.raises(Exception) as e_info:
        await derived_signal_backend.put(value = None, wait = False)
    assert type(e_info.value) == RuntimeError
    
    with pytest.raises(Exception) as e_info:
        await derived_signal_backend.put(value = None, wait = True)
    assert type(e_info.value) == RuntimeError

@patch("ophyd_async.core._derived_signal.get_type_hints", return_value={})
def test_get_return_datatype_no_type(movable_beamstop:MovableBeamstop):
    with pytest.raises(Exception) as e_info:
        _get_return_datatype(movable_beamstop._get_position)
    assert type(e_info.value) == TypeError

def test_get_return_datatype(movable_beamstop:MovableBeamstop):
    result = _get_return_datatype(movable_beamstop._get_position)
    assert isinstance(result,StrictEnumMeta)

@patch("ophyd_async.core._derived_signal.get_type_hints", return_value={})
def test_get_first_arg_datatype_no_type(movable_beamstop:MovableBeamstop):
    with pytest.raises(Exception) as e_info:
        _get_first_arg_datatype(movable_beamstop._set_from_position)
    assert type(e_info.value) == TypeError

def test_derived_signal_rw_type_error(movable_beamstop:MovableBeamstop):
    with patch.object(movable_beamstop, '_set_from_position', movable_beamstop._get_position):
        with pytest.raises(Exception) as e_info:
            derived_signal_rw(movable_beamstop._get_position,movable_beamstop._set_from_position)
        assert type(e_info.value) == TypeError

def test_make_rw_signal_type_mismatch(movable_beamstop:MovableBeamstop):
    factory = _make_factory(movable_beamstop._get_position, None, {"x":movable_beamstop.x, "y":movable_beamstop.y})
    with pytest.raises(Exception) as e_info:
        factory._make_signal(signal_cls=SignalRW, datatype=BeamstopPosition, name="")
    assert type(e_info.value) == ValueError