import asyncio
from typing import Dict
from unittest.mock import Mock, call, patch

import pytest
from bluesky.protocols import Reading

from ophyd_async.core import (
    DeviceCollector,
    NotConnected,
    set_mock_callback,
    set_mock_value,
)
from ophyd_async.epics import demo

# Long enough for multiple asyncio event loop cycles to run so
# all the tasks have a chance to run
A_WHILE = 0.001


@pytest.fixture
async def mock_mover():
    async with DeviceCollector(mock=True):
        mock_mover = demo.Mover("BLxxI-MO-TABLE-01:X:")
        # Signals connected here

    assert mock_mover.name == "mock_mover"
    set_mock_value(mock_mover.units, "mm")
    set_mock_value(mock_mover.precision, 3)
    set_mock_value(mock_mover.velocity, 1)
    yield mock_mover


@pytest.fixture
async def mock_sensor():
    async with DeviceCollector(mock=True):
        mock_sensor = demo.Sensor("MOCK:SENSOR:")
        # Signals connected here

    assert mock_sensor.name == "mock_sensor"
    yield mock_sensor


class Watcher:
    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._mock = Mock()

    def __call__(self, *args, **kwargs):
        self._mock(*args, **kwargs)
        self._event.set()

    async def wait_for_call(self, *args, **kwargs):
        await asyncio.wait_for(self._event.wait(), timeout=1)
        assert self._mock.call_count == 1
        assert self._mock.call_args == call(*args, **kwargs)
        self._mock.reset_mock()
        self._event.clear()


async def test_mover_moving_well(mock_mover: demo.Mover) -> None:
    s = mock_mover.set(0.55)
    watcher = Watcher()
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
    assert 0.55 == await mock_mover.setpoint.get_value()
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


async def test_mover_stopped(mock_mover: demo.Mover):
    callbacks = []
    set_mock_callback(mock_mover.stop_, lambda r, v: callbacks.append(v))

    assert callbacks == [None]
    await mock_mover.stop()
    assert callbacks == [None, None]


async def test_read_mover(mock_mover: demo.Mover):
    await mock_mover.stage()
    assert (await mock_mover.read())["mock_mover"]["value"] == 0.0
    assert (await mock_mover.describe())["mock_mover"][
        "source"
    ] == "mock://BLxxI-MO-TABLE-01:X:Readback"
    assert (await mock_mover.read_configuration())["mock_mover-velocity"]["value"] == 1
    assert (await mock_mover.describe_configuration())["mock_mover-units"]["shape"] == []
    set_mock_value(mock_mover.readback, 0.5)
    assert (await mock_mover.read())["mock_mover"]["value"] == 0.5
    await mock_mover.unstage()
    # Check we can still read and describe when not staged
    set_mock_value(mock_mover.readback, 0.1)
    assert (await mock_mover.read())["mock_mover"]["value"] == 0.1
    assert await mock_mover.describe()


async def test_set_velocity(mock_mover: demo.Mover) -> None:
    v = mock_mover.velocity
    assert (await v.describe())["mock_mover-velocity"][
        "source"
    ] == "mock://BLxxI-MO-TABLE-01:X:Velocity"
    q: asyncio.Queue[Dict[str, Reading]] = asyncio.Queue()
    v.subscribe(q.put_nowait)
    assert (await q.get())["mock_mover-velocity"]["value"] == 1.0
    await v.set(2.0)
    assert (await q.get())["mock_mover-velocity"]["value"] == 2.0
    v.clear_sub(q.put_nowait)
    await v.set(3.0)
    assert (await v.read())["mock_mover-velocity"]["value"] == 3.0
    assert q.empty()


async def test_mover_disconncted():
    with pytest.raises(NotConnected, match="Not all Devices connected"):
        async with DeviceCollector(timeout=0.1):
            m = demo.Mover("ca://PRE:", name="mover")
    assert m.name == "mover"


async def test_sensor_disconnected():
    with patch("ophyd_async.core.device.logging") as mock_logging:
        with pytest.raises(NotConnected, match="Not all Devices connected"):
            async with DeviceCollector(timeout=0.1):
                s = demo.Sensor("ca://PRE:", name="sensor")
        mock_logging.error.assert_called_once_with(
            """\
1 Devices did not connect:
  s: NotConnected
    value: ca://PRE:Value
    mode: ca://PRE:Mode"""
        )
    assert s.name == "sensor"


async def test_read_sensor(mock_sensor: demo.Sensor):
    mock_sensor.stage()
    assert (await mock_sensor.read())["mock_sensor-value"]["value"] == 0
    assert (await mock_sensor.describe())["mock_sensor-value"][
        "source"
    ] == "mock://MOCK:SENSOR:Value"
    assert (await mock_sensor.read_configuration())["mock_sensor-mode"][
        "value"
    ] == demo.EnergyMode.low
    desc = (await mock_sensor.describe_configuration())["mock_sensor-mode"]
    assert desc["dtype"] == "string"
    assert desc["choices"] == ["Low Energy", "High Energy"]  # type: ignore
    set_mock_value(mock_sensor.mode, demo.EnergyMode.high)
    assert (await mock_sensor.read_configuration())["mock_sensor-mode"][
        "value"
    ] == demo.EnergyMode.high
    await mock_sensor.unstage()


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


def test_mover_in_re(mock_mover: demo.Mover, RE) -> None:
    mock_mover.move(0)

    def my_plan():
        mock_mover.move(0)
        return
        yield

    with pytest.raises(RuntimeError, match="Will deadlock run engine if run in a plan"):
        RE(my_plan())
