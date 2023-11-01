import asyncio
from typing import Dict
from unittest.mock import Mock, call, patch

import pytest
from bluesky.protocols import Reading

from ophyd_async.core import (
    DeviceCollector,
    NotConnected,
    set_sim_callback,
    set_sim_value,
)
from ophyd_async.epics import demo

# Long enough for multiple asyncio event loop cycles to run so
# all the tasks have a chance to run
A_WHILE = 0.001


@pytest.fixture
async def sim_mover():
    async with DeviceCollector(sim=True):
        sim_mover = demo.Mover("BLxxI-MO-TABLE-01:X:")
        # Signals connected here

    assert sim_mover.name == "sim_mover"
    set_sim_value(sim_mover.units, "mm")
    set_sim_value(sim_mover.precision, 3)
    set_sim_value(sim_mover.velocity, 1)
    yield sim_mover


@pytest.fixture
async def sim_sensor():
    async with DeviceCollector(sim=True):
        sim_sensor = demo.Sensor("SIM:SENSOR:")
        # Signals connected here

    assert sim_sensor.name == "sim_sensor"
    yield sim_sensor


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


async def test_mover_moving_well(sim_mover: demo.Mover) -> None:
    s = sim_mover.set(0.55)
    watcher = Watcher()
    s.watch(watcher)
    done = Mock()
    s.add_callback(done)
    await watcher.wait_for_call(
        name="sim_mover",
        current=0.0,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.0, abs=0.05),
    )
    assert 0.55 == await sim_mover.setpoint.get_value()
    assert not s.done
    done.assert_not_called()
    await asyncio.sleep(0.1)
    set_sim_value(sim_mover.readback, 0.1)
    await watcher.wait_for_call(
        name="sim_mover",
        current=0.1,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.1, abs=0.05),
    )
    set_sim_value(sim_mover.readback, 0.5499999)
    await asyncio.sleep(A_WHILE)
    assert s.done
    assert s.success
    done.assert_called_once_with(s)
    done2 = Mock()
    s.add_callback(done2)
    done2.assert_called_once_with(s)


async def test_mover_stopped(sim_mover: demo.Mover):
    callbacks = []

    with set_sim_callback(sim_mover.stop_, lambda r, v: callbacks.append(v)):
        assert callbacks == [None]
        await sim_mover.stop()
        assert callbacks == [None, None]


async def test_read_mover(sim_mover: demo.Mover):
    await sim_mover.stage()
    assert (await sim_mover.read())["sim_mover"]["value"] == 0.0
    assert (await sim_mover.describe())["sim_mover"][
        "source"
    ] == "sim://BLxxI-MO-TABLE-01:X:Readback"
    assert (await sim_mover.read_configuration())["sim_mover-velocity"]["value"] == 1
    assert (await sim_mover.describe_configuration())["sim_mover-units"]["shape"] == []
    set_sim_value(sim_mover.readback, 0.5)
    assert (await sim_mover.read())["sim_mover"]["value"] == 0.5
    await sim_mover.unstage()
    # Check we can still read and describe when not staged
    set_sim_value(sim_mover.readback, 0.1)
    assert (await sim_mover.read())["sim_mover"]["value"] == 0.1
    assert await sim_mover.describe()


async def test_set_velocity(sim_mover: demo.Mover) -> None:
    v = sim_mover.velocity
    assert (await v.describe())["sim_mover-velocity"][
        "source"
    ] == "sim://BLxxI-MO-TABLE-01:X:Velocity"
    q: asyncio.Queue[Dict[str, Reading]] = asyncio.Queue()
    v.subscribe(q.put_nowait)
    assert (await q.get())["sim_mover-velocity"]["value"] == 1.0
    await v.set(2.0)
    assert (await q.get())["sim_mover-velocity"]["value"] == 2.0
    v.clear_sub(q.put_nowait)
    await v.set(3.0)
    assert (await v.read())["sim_mover-velocity"]["value"] == 3.0
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


async def test_read_sensor(sim_sensor: demo.Sensor):
    sim_sensor.stage()
    assert (await sim_sensor.read())["sim_sensor-value"]["value"] == 0
    assert (await sim_sensor.describe())["sim_sensor-value"][
        "source"
    ] == "sim://SIM:SENSOR:Value"
    assert (await sim_sensor.read_configuration())["sim_sensor-mode"][
        "value"
    ] == demo.EnergyMode.low
    desc = (await sim_sensor.describe_configuration())["sim_sensor-mode"]
    assert desc["dtype"] == "string"
    assert desc["choices"] == ["Low Energy", "High Energy"]  # type: ignore
    set_sim_value(sim_sensor.mode, demo.EnergyMode.high)
    assert (await sim_sensor.read_configuration())["sim_sensor-mode"][
        "value"
    ] == demo.EnergyMode.high
    await sim_sensor.unstage()


async def test_assembly_renaming() -> None:
    thing = demo.SampleStage("PRE")
    await thing.connect(sim=True)
    assert thing.x.name == ""
    assert thing.x.velocity.name == ""
    assert thing.x.stop_.name == ""
    await thing.x.velocity.set(456)
    assert await thing.x.velocity.get_value() == 456
    thing.set_name("foo")
    assert thing.x.name == "foo-x"
    assert thing.x.velocity.name == "foo-x-velocity"
    assert thing.x.stop_.name == "foo-x-stop"


def test_mover_in_re(sim_mover: demo.Mover, RE) -> None:
    sim_mover.move(0)

    def my_plan():
        sim_mover.move(0)
        return
        yield

    with pytest.raises(RuntimeError, match="Will deadlock run engine if run in a plan"):
        RE(my_plan())
