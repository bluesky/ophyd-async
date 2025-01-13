import asyncio
from collections import defaultdict
from unittest.mock import ANY, Mock, call

import pytest
from bluesky import plans as bp
from bluesky.protocols import Reading
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    LazyMock,
    NotConnected,
    init_devices,
)
from ophyd_async.epics import demo
from ophyd_async.testing import (
    assert_emitted,
    assert_reading,
    assert_value,
    callback_on_mock_put,
    get_mock,
    get_mock_put,
    set_mock_value,
    wait_for_pending_wakeups,
)


@pytest.fixture
async def mock_motor() -> demo.DemoMotor:
    async with init_devices(mock=True):
        mock_motor = demo.DemoMotor("BLxxI-MO-TABLE-01:X:")
        # Signals connected here

    assert mock_motor.name == "mock_motor"
    set_mock_value(mock_motor.units, "mm")
    set_mock_value(mock_motor.precision, 3)
    set_mock_value(mock_motor.velocity, 1)
    return mock_motor


@pytest.fixture
async def mock_point_detector() -> demo.DemoPointDetector:
    async with init_devices(mock=True):
        mock_point_detector = demo.DemoPointDetector("MOCK:DET:")
        # Signals connected here

    assert mock_point_detector.name == "mock_point_detector"
    return mock_point_detector


async def test_motor_stopped(mock_motor: demo.DemoMotor):
    callbacks = []
    callback_on_mock_put(
        mock_motor.stop_, lambda v, *args, **kwargs: callbacks.append(v)
    )

    await mock_motor.stop()
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


async def test_motor_moving_well(mock_motor: demo.DemoMotor) -> None:
    s = mock_motor.set(0.55)
    watcher = DemoWatcher()
    s.watch(watcher)
    done = Mock()
    s.add_callback(done)
    await watcher.wait_for_call(
        name="mock_motor",
        current=0.0,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.0, abs=0.08),
    )

    await assert_value(mock_motor.setpoint, 0.55)
    assert not s.done
    done.assert_not_called()
    await asyncio.sleep(0.1)
    set_mock_value(mock_motor.readback, 0.1)
    await watcher.wait_for_call(
        name="mock_motor",
        current=0.1,
        initial=0.0,
        target=0.55,
        unit="mm",
        precision=3,
        time_elapsed=pytest.approx(0.1, abs=0.08),
    )
    set_mock_value(mock_motor.readback, 0.5499999)
    await wait_for_pending_wakeups()
    assert s.done
    assert s.success
    done.assert_called_once_with(s)
    done2 = Mock()
    s.add_callback(done2)
    done2.assert_called_once_with(s)


async def test_retrieve_mock_and_assert(mock_motor: demo.DemoMotor):
    motor_setpoint_mock = get_mock_put(mock_motor.setpoint)
    await mock_motor.setpoint.set(10)
    motor_setpoint_mock.assert_called_once_with(10, wait=ANY)

    # Assert that velocity is set before move
    motor_velocity_mock = get_mock_put(mock_motor.velocity)

    parent_mock = Mock()
    parent_mock.attach_mock(motor_setpoint_mock, "setpoint")
    parent_mock.attach_mock(motor_velocity_mock, "velocity")

    await mock_motor.velocity.set(100)
    await mock_motor.setpoint.set(67)
    assert parent_mock.mock_calls == [
        call.velocity(100, wait=True),
        call.setpoint(67, wait=True),
    ]


async def test_mocks_in_device_share_parent():
    lm = LazyMock()
    mock_motor = demo.DemoMotor("BLxxI-MO-TABLE-01:Y:")
    await mock_motor.connect(mock=lm)
    mock = lm()

    assert get_mock(mock_motor) is mock
    assert get_mock(mock_motor.setpoint) is mock.setpoint
    assert get_mock_put(mock_motor.setpoint) is mock.setpoint.put
    await mock_motor.setpoint.set(10)
    get_mock_put(mock_motor.setpoint).assert_called_once_with(10, wait=ANY)

    await mock_motor.velocity.set(100)
    await mock_motor.setpoint.set(67)

    mock.reset_mock()
    await mock_motor.velocity.set(100)
    await mock_motor.setpoint.set(67)
    assert mock.mock_calls == [
        call.velocity.put(100, wait=True),
        call.setpoint.put(67, wait=True),
    ]


async def test_read_motor(mock_motor: demo.DemoMotor):
    await mock_motor.stage()
    assert (await mock_motor.read())["mock_motor"]["value"] == 0.0
    assert (await mock_motor.read_configuration())["mock_motor-velocity"]["value"] == 1
    assert (await mock_motor.describe_configuration())["mock_motor-units"][
        "shape"
    ] == []
    set_mock_value(mock_motor.readback, 0.5)
    assert (await mock_motor.read())["mock_motor"]["value"] == 0.5
    await mock_motor.unstage()
    # Check we can still read and describe when not staged
    set_mock_value(mock_motor.readback, 0.1)
    assert (await mock_motor.read())["mock_motor"]["value"] == 0.1
    assert await mock_motor.describe()


async def test_set_velocity(mock_motor: demo.DemoMotor) -> None:
    v = mock_motor.velocity
    q: asyncio.Queue[dict[str, Reading]] = asyncio.Queue()
    v.subscribe(q.put_nowait)
    assert (await q.get())["mock_motor-velocity"]["value"] == 1.0
    await v.set(2.0)
    assert (await q.get())["mock_motor-velocity"]["value"] == 2.0
    v.clear_sub(q.put_nowait)
    await v.set(3.0)
    assert (await v.read())["mock_motor-velocity"]["value"] == 3.0
    assert q.empty()


async def test_zero_velocity(mock_motor: demo.DemoMotor) -> None:
    # v = sim_motor.velocity
    await mock_motor.velocity.set(0)
    with pytest.raises(ValueError, match="Mover has zero velocity"):
        await mock_motor.set(3.14)


async def test_mover_disconnected():
    with pytest.raises(NotConnected):
        async with init_devices(timeout=0.1):
            m = demo.DemoMotor("ca://PRE:", name="motor")
    assert m.name == "motor"


async def test_read_point_detector(mock_point_detector: demo.DemoPointDetector):
    channel = mock_point_detector.channel[1]
    assert (await channel.read())["mock_point_detector-channel-1-value"]["value"] == 0
    assert (await channel.read_configuration())["mock_point_detector-channel-1-mode"][
        "value"
    ] == demo.EnergyMode.LOW
    desc = (await channel.describe_configuration())[
        "mock_point_detector-channel-1-mode"
    ]
    assert desc["dtype"] == "string"
    assert desc["choices"] == ["Low Energy", "High Energy"]
    set_mock_value(channel.mode, demo.EnergyMode.HIGH)
    assert (await channel.read_configuration())["mock_point_detector-channel-1-mode"][
        "value"
    ] == demo.EnergyMode.HIGH


async def test_point_detector_in_plan(
    RE: RunEngine, mock_point_detector: demo.DemoPointDetector
):
    """Tests mock point_detector behavior within a RunEngine plan.

    This test verifies that the point_detector emits the expected documents
     when used in plan(count).
    """
    docs = defaultdict(list)
    RE.subscribe(lambda name, doc: docs[name].append(doc))

    RE(bp.count([mock_point_detector], num=2))
    assert_emitted(docs, start=1, descriptor=1, event=2, stop=1)


async def test_assembly_renaming() -> None:
    thing = demo.DemoStage("PRE")
    await thing.connect(mock=True)
    assert thing.x.name == ""
    assert thing.x.velocity.name == ""
    assert thing.x.stop_.name == ""
    await thing.x.velocity.set(456)
    assert await thing.x.velocity.get_value() == 456
    thing.set_name("foo")
    assert thing.x.name == "foo-x"
    assert thing.x.velocity.name == "foo-x-velocity"
    assert thing.x.stop_.name == "foo-x-stop_"


async def test_point_detector_disconnected():
    with pytest.raises(NotConnected) as e:
        async with init_devices(timeout=0.1):
            det = demo.DemoPointDetector("MOCK:DET:")
    expected = """
det: NotConnected:
    channel: NotConnected:
        1: NotConnected:
            value: NotConnected: ca://MOCK:DET:1:Value
            mode: NotConnected: ca://MOCK:DET:1:Mode
        2: NotConnected:
            value: NotConnected: ca://MOCK:DET:2:Value
            mode: NotConnected: ca://MOCK:DET:2:Mode
        3: NotConnected:
            value: NotConnected: ca://MOCK:DET:3:Value
            mode: NotConnected: ca://MOCK:DET:3:Mode
    acquire_time: NotConnected: ca://MOCK:DET:AcquireTime
    start: NotConnected: ca://MOCK:DET:Start.PROC
    acquiring: NotConnected: ca://MOCK:DET:Acquiring
    reset: NotConnected: ca://MOCK:DET:Reset.PROC
"""
    assert str(e.value) == expected

    assert det.name == "det"


async def test_point_detector_read_and_describe(
    mock_point_detector: demo.DemoPointDetector,
):
    set_mock_value(mock_point_detector.channel[1].value, 1)
    set_mock_value(mock_point_detector.channel[2].value, 5)
    set_mock_value(mock_point_detector.channel[3].value, 10)

    await mock_point_detector.stage()
    description = await mock_point_detector.describe()

    await mock_point_detector.unstage()
    await assert_reading(
        mock_point_detector,
        {
            "mock_point_detector-channel-1-value": {
                "value": 1,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
            "mock_point_detector-channel-2-value": {
                "value": 5,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
            "mock_point_detector-channel-3-value": {
                "value": 10,
                "timestamp": ANY,
                "alarm_severity": 0,
            },
        },
    )
    assert description == {
        "mock_point_detector-channel-1-value": {
            "dtype": "integer",
            "dtype_numpy": "<i8",
            "shape": [],
            "source": "mock+ca://MOCK:DET:1:Value",
        },
        "mock_point_detector-channel-2-value": {
            "dtype": "integer",
            "dtype_numpy": "<i8",
            "shape": [],
            "source": "mock+ca://MOCK:DET:2:Value",
        },
        "mock_point_detector-channel-3-value": {
            "dtype": "integer",
            "dtype_numpy": "<i8",
            "shape": [],
            "source": "mock+ca://MOCK:DET:3:Value",
        },
    }
