import asyncio
import subprocess
from collections import defaultdict
from unittest.mock import ANY, Mock, call, patch

import pytest
from bluesky import plans as bp
from bluesky.protocols import Reading
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DeviceCollector,
    NotConnected,
    assert_emitted,
    assert_reading,
    assert_value,
    callback_on_mock_put,
    get_mock_put,
    set_mock_value,
)
from ophyd_async.epics import demo

# Long enough for multiple asyncio event loop cycles to run so
# all the tasks have a chance to run
A_WHILE = 0.001


@pytest.fixture
async def mock_mover() -> demo.Mover:
    async with DeviceCollector(mock=True):
        mock_mover = demo.Mover("BLxxI-MO-TABLE-01:X:")
        # Signals connected here

    assert mock_mover.name == "mock_mover"
    set_mock_value(mock_mover.units, "mm")
    set_mock_value(mock_mover.precision, 3)
    set_mock_value(mock_mover.velocity, 1)
    return mock_mover


@pytest.fixture
async def mock_sensor() -> demo.Sensor:
    async with DeviceCollector(mock=True):
        mock_sensor = demo.Sensor("MOCK:SENSOR:")
        # Signals connected here

    assert mock_sensor.name == "mock_sensor"
    return mock_sensor


@pytest.fixture
async def mock_sensor_group() -> demo.SensorGroup:
    async with DeviceCollector(mock=True):
        mock_sensor_group = demo.SensorGroup("MOCK:SENSOR:")
        # Signals connected here

    assert mock_sensor_group.name == "mock_sensor_group"
    return mock_sensor_group


async def test_mover_stopped(mock_mover: demo.Mover):
    callbacks = []
    callback_on_mock_put(
        mock_mover.stop_, lambda v, *args, **kwargs: callbacks.append(v)
    )

    await mock_mover.stop()
    assert callbacks == [None]


class DemoWatcher:
    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._mock = Mock()

    def __call__(
        self,
        *args,
        current: float,
        initial: float,
        target: float,
        name: str | None = None,
        unit: str | None = None,
        precision: float | None = None,
        fraction: float | None = None,
        time_elapsed: float | None = None,
        time_remaining: float | None = None,
        **kwargs,
    ):
        self._mock(
            *args,
            current=current,
            initial=initial,
            target=target,
            name=name,
            unit=unit,
            precision=precision,
            time_elapsed=time_elapsed,
            **kwargs,
        )
        self._event.set()

    async def wait_for_call(self, *args, **kwargs):
        await asyncio.wait_for(self._event.wait(), timeout=1)
        assert self._mock.call_count == 1
        assert self._mock.call_args == call(*args, **kwargs)
        self._mock.reset_mock()
        self._event.clear()


async def test_mover_moving_well(mock_mover: demo.Mover) -> None:
    s = mock_mover.set(0.55)
    watcher = DemoWatcher()
    s.watch(watcher)
    done = Mock()
    s.add_callback(done)
    await watcher.wait_for_call(
        name="mock_mover",
        current=0.0,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.0, abs=0.05),
    )

    await assert_value(mock_mover.setpoint, 0.55)
    assert not s.done
    done.assert_not_called()
    await asyncio.sleep(0.1)
    set_mock_value(mock_mover.readback, 0.1)
    await watcher.wait_for_call(
        name="mock_mover",
        current=0.1,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.1, abs=0.05),
    )
    set_mock_value(mock_mover.readback, 0.5499999)
    await asyncio.sleep(A_WHILE)
    assert s.done
    assert s.success
    done.assert_called_once_with(s)
    done2 = Mock()
    s.add_callback(done2)
    done2.assert_called_once_with(s)


async def test_sensor_reading_shows_value(mock_sensor: demo.Sensor):
    # Check default value
    await assert_value(mock_sensor.value, pytest.approx(0.0))
    assert (await mock_sensor.value.get_value()) == pytest.approx(0.0)
    await assert_reading(
        mock_sensor,
        {
            "mock_sensor-value": {
                "value": 0.0,
                "alarm_severity": 0,
                "timestamp": ANY,
            }
        },
    )
    # Check different value
    set_mock_value(mock_sensor.value, 5.0)
    await assert_reading(
        mock_sensor,
        {
            "mock_sensor-value": {
                "value": 5.0,
                "timestamp": ANY,
                "alarm_severity": 0,
            }
        },
    )


async def test_retrieve_mock_and_assert(mock_mover: demo.Mover):
    mover_setpoint_mock = get_mock_put(mock_mover.setpoint)
    await mock_mover.setpoint.set(10)
    mover_setpoint_mock.assert_called_once_with(10, wait=ANY, timeout=ANY)

    # Assert that velocity is set before move
    mover_velocity_mock = get_mock_put(mock_mover.velocity)

    parent_mock = Mock()
    parent_mock.attach_mock(mover_setpoint_mock, "setpoint")
    parent_mock.attach_mock(mover_velocity_mock, "velocity")

    await mock_mover.velocity.set(100)
    await mock_mover.setpoint.set(67)

    parent_mock.assert_has_calls(
        [
            call.velocity(100, wait=True, timeout=ANY),
            call.setpoint(67, wait=True, timeout=ANY),
        ]
    )


async def test_read_mover(mock_mover: demo.Mover):
    await mock_mover.stage()
    assert (await mock_mover.read())["mock_mover"]["value"] == 0.0
    assert (await mock_mover.read_configuration())["mock_mover-velocity"]["value"] == 1
    assert (await mock_mover.describe_configuration())["mock_mover-units"][
        "shape"
    ] == []
    set_mock_value(mock_mover.readback, 0.5)
    assert (await mock_mover.read())["mock_mover"]["value"] == 0.5
    await mock_mover.unstage()
    # Check we can still read and describe when not staged
    set_mock_value(mock_mover.readback, 0.1)
    assert (await mock_mover.read())["mock_mover"]["value"] == 0.1
    assert await mock_mover.describe()


async def test_set_velocity(mock_mover: demo.Mover) -> None:
    v = mock_mover.velocity
    q: asyncio.Queue[dict[str, Reading]] = asyncio.Queue()
    v.subscribe(q.put_nowait)
    assert (await q.get())["mock_mover-velocity"]["value"] == 1.0
    await v.set(2.0)
    assert (await q.get())["mock_mover-velocity"]["value"] == 2.0
    v.clear_sub(q.put_nowait)
    await v.set(3.0)
    assert (await v.read())["mock_mover-velocity"]["value"] == 3.0
    assert q.empty()


async def test_mover_disconnected():
    with pytest.raises(NotConnected):
        async with DeviceCollector(timeout=0.1):
            m = demo.Mover("ca://PRE:", name="mover")
    assert m.name == "mover"


async def test_sensor_disconnected(caplog):
    caplog.set_level(10)
    with pytest.raises(NotConnected):
        async with DeviceCollector(timeout=0.1):
            s = demo.Sensor("ca://PRE:", name="sensor")
    logs = caplog.get_records("call")
    logs = [log for log in logs if "_signal" not in log.pathname]
    assert len(logs) == 2

    assert logs[0].message == ("signal ca://PRE:Value timed out")
    assert logs[1].message == ("signal ca://PRE:Mode timed out")
    assert s.name == "sensor"


async def test_read_sensor(mock_sensor: demo.Sensor):
    mock_sensor.stage()
    assert (await mock_sensor.read())["mock_sensor-value"]["value"] == 0
    assert (await mock_sensor.read_configuration())["mock_sensor-mode"][
        "value"
    ] == demo.EnergyMode.low
    desc = (await mock_sensor.describe_configuration())["mock_sensor-mode"]
    assert desc["dtype"] == "string"
    assert desc["choices"] == ("Low Energy", "High Energy")  # type: ignore
    set_mock_value(mock_sensor.mode, demo.EnergyMode.high)
    assert (await mock_sensor.read_configuration())["mock_sensor-mode"][
        "value"
    ] == demo.EnergyMode.high
    await mock_sensor.unstage()


async def test_sensor_in_plan(RE: RunEngine, mock_sensor: demo.Sensor):
    """Tests mock sensor behavior within a RunEngine plan.

    This test verifies that the sensor emits the expected documents
     when used in plan(count).
    """
    docs = defaultdict(list)

    def capture_emitted(name, doc):
        docs[name].append(doc)

    RE(bp.count([mock_sensor], num=2), capture_emitted)
    assert_emitted(docs, start=1, descriptor=1, event=2, stop=1)


async def test_assembly_renaming() -> None:
    thing = demo.SampleStage("PRE")
    await thing.connect(mock=True)
    assert thing.x.name == ""
    assert thing.x.velocity.name == ""
    assert thing.x.stop_.name == ""
    await thing.x.velocity.set(456)
    assert await thing.x.velocity.get_value() == 456
    thing.set_name("foo")
    assert thing.x.name == "foo-x"
    assert thing.x.velocity.name == "foo-x-velocity"
    assert thing.x.stop_.name == "foo-x-stop"


async def test_dynamic_sensor_group_disconnected():
    with pytest.raises(NotConnected):
        async with DeviceCollector(timeout=0.1):
            mock_sensor_group_dynamic = demo.SensorGroup("MOCK:SENSOR:")

    assert mock_sensor_group_dynamic.name == "mock_sensor_group_dynamic"


async def test_dynamic_sensor_group_read_and_describe(
    mock_sensor_group: demo.SensorGroup,
):
    set_mock_value(mock_sensor_group.sensors[1].value, 0.0)
    set_mock_value(mock_sensor_group.sensors[2].value, 0.5)
    set_mock_value(mock_sensor_group.sensors[3].value, 1.0)

    await mock_sensor_group.stage()
    description = await mock_sensor_group.describe()

    await mock_sensor_group.unstage()
    await assert_reading(
        mock_sensor_group,
        {
            "mock_sensor_group-sensors-1-value": {
                "value": 0.0,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
            "mock_sensor_group-sensors-2-value": {
                "value": 0.5,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
            "mock_sensor_group-sensors-3-value": {
                "value": 1.0,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
        },
    )
    assert description == {
        "mock_sensor_group-sensors-1-value": {
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
            "source": "mock+ca://MOCK:SENSOR:1:Value",
        },
        "mock_sensor_group-sensors-2-value": {
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
            "source": "mock+ca://MOCK:SENSOR:2:Value",
        },
        "mock_sensor_group-sensors-3-value": {
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
            "source": "mock+ca://MOCK:SENSOR:3:Value",
        },
    }


@patch("ophyd_async.epics.demo.subprocess.Popen")
async def test_ioc_starts(mock_popen: Mock):
    demo.start_ioc_subprocess()
    mock_popen.assert_called_once_with(
        ANY,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )
