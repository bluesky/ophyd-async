import asyncio
import subprocess
from collections import defaultdict
from typing import Dict
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
    set_sim_callback,
    set_sim_value,
)
from ophyd_async.epics import demo

# Long enough for multiple asyncio event loop cycles to run so
# all the tasks have a chance to run
A_WHILE = 0.001


@pytest.fixture
async def sim_mover() -> demo.Mover:
    async with DeviceCollector(sim=True):
        sim_mover = demo.Mover("BLxxI-MO-TABLE-01:X:")
        # Signals connected here

    assert sim_mover.name == "sim_mover"
    set_sim_value(sim_mover.units, "mm")
    set_sim_value(sim_mover.precision, 3)
    set_sim_value(sim_mover.velocity, 1)
    return sim_mover


@pytest.fixture
async def sim_sensor() -> demo.Sensor:
    async with DeviceCollector(sim=True):
        sim_sensor = demo.Sensor("SIM:SENSOR:")
        # Signals connected here

    assert sim_sensor.name == "sim_sensor"
    return sim_sensor


@pytest.fixture
async def sim_sensor_group() -> demo.SensorGroup:
    async with DeviceCollector(sim=True):
        sim_sensor_group = demo.SensorGroup("SIM:SENSOR:")
        # Signals connected here

    assert sim_sensor_group.name == "sim_sensor_group"
    return sim_sensor_group


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

    await assert_value(sim_mover.setpoint, 0.55)
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


async def test_sensor_reading_shows_value(sim_sensor: demo.Sensor):
    # Check default value
    await assert_value(sim_sensor.value, pytest.approx(0.0))
    assert (await sim_sensor.value.get_value()) == pytest.approx(0.0)
    await assert_reading(
        sim_sensor,
        {
            "sim_sensor-value": {
                "value": 0.0,
                "alarm_severity": 0,
                "timestamp": ANY,
            }
        },
    )
    # Check different value
    set_sim_value(sim_sensor.value, 5.0)
    await assert_reading(
        sim_sensor,
        {
            "sim_sensor-value": {
                "value": 5.0,
                "timestamp": ANY,
                "alarm_severity": 0,
            }
        },
    )


async def test_mover_stopped(sim_mover: demo.Mover):
    callbacks = []
    set_sim_callback(sim_mover.stop_, lambda r, v: callbacks.append(v))

    assert callbacks == [None]
    await sim_mover.stop()
    assert callbacks == [None, None]


async def test_read_mover(sim_mover: demo.Mover):
    await sim_mover.stage()
    assert (await sim_mover.read())["sim_mover"]["value"] == 0.0
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
    with pytest.raises(NotConnected):
        async with DeviceCollector(timeout=0.1):
            m = demo.Mover("ca://PRE:", name="mover")
        assert m.name == "mover"


async def test_sensor_disconnected(caplog):
    caplog.set_level(10)
    with pytest.raises(NotConnected):
        async with DeviceCollector(timeout=0.1):
            s = demo.Sensor("ca://PRE:", name="sensor")
        assert s.name == "sensor"
    logs = caplog.get_records("call")
    assert len(logs) == 2

    assert logs[0].message == ("signal ca://PRE:Value timed out")
    assert logs[1].message == ("signal ca://PRE:Mode timed out")


async def test_read_sensor(sim_sensor: demo.Sensor):
    sim_sensor.stage()
    assert (await sim_sensor.read())["sim_sensor-value"]["value"] == 0
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


async def test_sensor_in_plan(RE: RunEngine, sim_sensor: demo.Sensor):
    """Tests sim sensor behavior within a RunEngine plan.

    This test verifies that the sensor emits the expected documents
     when used in plan(count).
    """
    docs = defaultdict(list)

    def capture_emitted(name, doc):
        docs[name].append(doc)

    RE(bp.count([sim_sensor], num=2), capture_emitted)
    assert_emitted(docs, start=1, descriptor=1, event=2, stop=1)


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


async def test_dynamic_sensor_group_disconnected():
    with pytest.raises(NotConnected):
        async with DeviceCollector(timeout=0.1):
            sim_sensor_group_dynamic = demo.SensorGroup("SIM:SENSOR:")

        assert sim_sensor_group_dynamic.name == "sim_sensor_group_dynamic"


async def test_dynamic_sensor_group_read_and_describe(
    sim_sensor_group: demo.SensorGroup,
):
    set_sim_value(sim_sensor_group.sensors[1].value, 0.0)
    set_sim_value(sim_sensor_group.sensors[2].value, 0.5)
    set_sim_value(sim_sensor_group.sensors[3].value, 1.0)

    await sim_sensor_group.stage()
    description = await sim_sensor_group.describe()

    await sim_sensor_group.unstage()
    await assert_reading(
        sim_sensor_group,
        {
            "sim_sensor_group-sensors-1-value": {
                "value": 0.0,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
            "sim_sensor_group-sensors-2-value": {
                "value": 0.5,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
            "sim_sensor_group-sensors-3-value": {
                "value": 1.0,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
        },
    )
    assert description == {
        "sim_sensor_group-sensors-1-value": {
            "dtype": "number",
            "shape": [],
            "source": "soft://sim_sensor_group-sensors-1-value",
        },
        "sim_sensor_group-sensors-2-value": {
            "dtype": "number",
            "shape": [],
            "source": "soft://sim_sensor_group-sensors-2-value",
        },
        "sim_sensor_group-sensors-3-value": {
            "dtype": "number",
            "shape": [],
            "source": "soft://sim_sensor_group-sensors-3-value",
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
