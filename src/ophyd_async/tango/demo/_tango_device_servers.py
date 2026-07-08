"""Run the Tango device servers backing the `ophyd_async.tango.demo` tutorial.

Genuinely standalone: nothing in this file imports anything from `ophyd_async`
- only `tango`/`tango.server` and stdlib. That's deliberate, not incidental: it
means this file can be copied into (or run from) a separate PyTango-only venv
that doesn't have `ophyd_async` installed at all, exactly as a real `softIoc`
binary doesn't need whatever's launching it to be Python.

No configuration beyond a prefix - every device name served is fixed (see the
module-level constants and `predict_trl`), so nothing is ever read back about what
got served: exactly how a real `softIoc -d some.db -m "PREFIX:"` never reports its
PV names back either, since they're fixed by the `.db` file and only the macro
prefix varies. Run directly with a plain PyTango interpreter, by file path (not
`-m ophyd_async...`, which would need `ophyd_async` importable) - this is also
exactly how `ophyd_async.tango.testing.start_tango_device_servers` itself
launches it, so there's no separate "standalone" code path to keep working:

    tango-venv/bin/python \
        /path/to/ophyd_async/tango/demo/_tango_device_servers.py test/abc

It prints a readiness marker once serving, then blocks until stdin closes (or EOFs),
at which point it exits. To actually launch it as a managed subprocess from
ophyd_async client code, see `ophyd_async.tango.testing.start_tango_device_servers`
(in `_launch.py`, not this file - that one *does* need `ophyd_async.testing`, so
it's kept separate to avoid pulling that dependency into this standalone-runnable
file).

Serves `DemoMotorDevice`/`DemoMultiChannelDetectorDevice`/
`DemoPointDetectorChannelDevice` (below), which all need `GreenMode.Asyncio` for
their `asyncio.sleep`-based movement/acquisition simulation - a separate
module/process from `ophyd_async.tango.testing`'s test-only device servers
(which use the default sync green mode - PyTango only allows one green mode
per device server process). A topology needing both catalogs (e.g. the system
test suite) starts this module's servers and `ophyd_async.tango.testing`'s
independently, under the same prefix - see `tests/system_tests_tango/conftest.py`.

- `DemoMotorDevice`: backs `DemoMotor`/`DemoStage`.
- `DemoMultiChannelDetectorDevice`/`DemoPointDetectorChannelDevice`: back
  `DemoPointDetector`/`DemoPointDetectorChannel`.
"""

import asyncio
import math
import sys
import zlib
from enum import IntEnum

import tango
from tango import AttrWriteType, DevState, GreenMode
from tango.asyncio import DeviceProxy

_READY_MARKER = "TANGO_DEVICE_SERVERS_READY"

# Deterministic port: derived from the prefix so a caller can predict the TRL
# without anything being read back (see predict_trl). Chosen to sit below
# Linux's default ephemeral port range (typically 32768-60999) to minimise the
# (already small) chance of colliding with an unrelated OS-assigned port on the
# same machine, and to sit in a distinct range from
# `ophyd_async.tango.testing._tango_device_servers`'s so the two can be started
# under the same prefix without colliding.
_PORT_BASE = 30000
_PORT_RANGE = 10000

# Fixed device names served under any given prefix.
MOTOR_X = "motor-x"
MOTOR_Y = "motor-y"
CHANNEL_1 = "channel-1"
CHANNEL_2 = "channel-2"
CHANNEL_3 = "channel-3"
DETECTOR = "detector"
CHANNEL_NAMES = (CHANNEL_1, CHANNEL_2, CHANNEL_3)
NUM_CHANNELS = len(CHANNEL_NAMES)
ALL_DEVICE_NAMES = (MOTOR_X, MOTOR_Y, *CHANNEL_NAMES, DETECTOR)


def _device_classes():
    """Build the Demo*Device classes.

    Deferring the tango.server import until actually needed (only inside
    _serve) - so merely importing this module (e.g. for predict_trl) never
    pulls tango.server in.
    """
    from tango.server import Device, attribute, command, device_property

    class DemoMotorDevice(Device):
        """Demo tango moving device."""

        green_mode = GreenMode.Asyncio
        _position = 0.0
        _setpoint = 0.0
        _velocity = 1.0
        _acceleration = 1.0
        _stop = False
        DEVICE_CLASS_INITIAL_STATE = DevState.ON

        @attribute(dtype=float, access=AttrWriteType.READ, format="%6.3f")
        async def readback(self):
            return self._position

        @attribute(dtype=float, access=AttrWriteType.READ_WRITE, format="%6.3f")
        async def setpoint(self):
            return self._setpoint

        async def write_setpoint(self, new_position):
            self.set_state(DevState.MOVING)
            self._setpoint = new_position
            asyncio.create_task(self.move())

        @attribute(dtype=float, access=AttrWriteType.READ_WRITE)
        async def velocity(self):
            return self._velocity

        async def write_velocity(self, value: float):
            self._velocity = value

        @attribute(dtype=DevState, access=AttrWriteType.READ)
        async def state(self):
            return self.get_state()

        @command
        async def stop(self):
            self._stop = True

        @command
        async def move(self):
            self.set_state(DevState.MOVING)
            self._stop = False
            step = 0.1
            while True:
                if self._stop:
                    self._stop = False
                    break
                if abs(self._position - self._setpoint) < abs(self._velocity * step):
                    self._position = self._setpoint
                    break
                if self._position < self._setpoint:
                    self._position = self._position + self._velocity * step
                else:
                    self._position = self._position - self._velocity * step
                await asyncio.sleep(step)
            self.set_state(DevState.ON)

    class Mode(IntEnum):
        LOW = 0
        HIGH = 1

    class DemoMultiChannelDetectorDevice(Device):
        """Demo tango counting device."""

        channels = device_property(dtype=int, default_value=0)

        green_mode = GreenMode.Asyncio
        _acquire_time = 0.1
        _acquiring = False
        _elapsed = 0.0

        async def init_device(self):
            await super().init_device()
            self._locators = []
            self._dps = []

        @attribute(dtype=(str,), max_dim_x=32, access=AttrWriteType.READ_WRITE)
        async def locators(self):
            return self._locators

        async def write_locators(self, value: (str)):
            self._locators = value

        @attribute(dtype=float, access=AttrWriteType.READ_WRITE)
        async def acquire_time(self):
            return self._acquire_time

        async def write_acquire_time(self, value: float):
            self._acquire_time = value

        @attribute(dtype=bool, access=AttrWriteType.READ)
        async def acquiring(self):
            return self._acquiring

        @attribute(dtype=float, access=AttrWriteType.READ)
        async def elapsed(self):
            return self._elapsed

        @attribute(dtype=DevState, access=AttrWriteType.READ)
        async def state(self):
            return self.get_state()

        @command
        async def connect_devices(self):
            for locator in self._locators:
                # Connect by tango device proxy to the X motor
                self._dps.append(await DeviceProxy(locator))  # type: ignore

        @command
        async def start(self):
            await self._acquisition()

        @command
        async def reset(self):
            self._elapsed = 0.0

        async def _acquisition(self):
            self._acquiring = True
            self._elapsed = 0.0
            step = 0.1
            while self._elapsed < self._acquire_time:
                self._elapsed += step
                # Send the elapsed update to the channels
                for dps in self._dps:
                    dps.elapsed = self._elapsed
                await asyncio.sleep(step)
            self._elapsed = self._acquire_time
            for dps in self._dps:
                dps.elapsed = self._acquire_time
            await asyncio.sleep(step)
            self._acquiring = False

    class DemoPointDetectorChannelDevice(Device):
        """Demo tango counting device."""

        channel: device_property = device_property(dtype=int, default_value=0)

        green_mode = GreenMode.Asyncio
        _value = 0
        _locator_x = ""
        _locator_y = ""
        _elapsed = 0.0
        _dp_x: Device | None = None
        _dp_y = None
        _mode: Mode = Mode.LOW
        _energy_modes = [10, 100]

        @attribute(dtype=str, access=AttrWriteType.READ_WRITE)
        async def locator_x(self):
            return self._locator_x

        async def write_locator_x(self, value: str):
            self._locator_x = value

        @attribute(dtype=str, access=AttrWriteType.READ_WRITE)
        async def locator_y(self):
            return self._locator_y

        async def write_locator_y(self, value: str):
            self._locator_y = value

        @attribute(dtype=Mode, access=AttrWriteType.READ_WRITE)
        async def mode(self):
            return self._mode

        async def write_mode(self, value: Mode):
            self._mode = value

        @attribute(dtype=float, access=AttrWriteType.READ_WRITE)
        async def elapsed(self):
            return self._elapsed

        async def write_elapsed(self, value: float):
            self._elapsed = value
            x: float = await self._dp_x.readback  # type: ignore
            y: float = await self._dp_y.readback  # type: ignore
            self._value = math.floor(
                (
                    math.sin(x) ** self.channel  # type: ignore
                    + math.cos(x * y + self._energy_modes[self._mode])
                    + 2
                )
                * 2500
                * self._elapsed
            )  # type: ignore

        @command
        async def connect_devices(self):
            # Connect by tango device proxy to the X motor
            self._dp_x = await DeviceProxy(self._locator_x)  # type: ignore
            # Connect by tango device proxy to the Y motor
            self._dp_y = await DeviceProxy(self._locator_y)  # type: ignore

        @attribute(dtype=int, access=AttrWriteType.READ)
        async def value(self):
            return self._value

    return (
        DemoMotorDevice,
        DemoMultiChannelDetectorDevice,
        DemoPointDetectorChannelDevice,
    )


def _port_for_prefix(prefix: str) -> int:
    """Deterministically derive the process port from `prefix`.

    Not Python's randomised `hash()` - this must be stable across
    processes/runs.
    """
    return _PORT_BASE + (zlib.crc32(prefix.encode()) % _PORT_RANGE)


def predict_trl(prefix: str, device_name: str) -> str:
    """Predict the TRL `tango_device_servers_args(prefix)` serves `device_name` at.

    `device_name` is one of the module-level constants above (e.g. `DETECTOR`).
    Works without starting anything - the whole point of a fixed, prefix-derived
    port and fixed device names is that this is computable up front.
    """
    port = _port_for_prefix(prefix)
    return f"tango://127.0.0.1:{port}/{prefix}/{device_name}#dbase=no"


def tango_device_servers_args(prefix: str) -> list[str]:
    """Build the `<file> <prefix>` argv for the fixed set of demo device servers.

    Points at this file *by path* (`__file__`), not `-m ophyd_async...` - so the
    exact same argv works verbatim from a venv that doesn't have `ophyd_async`
    installed at all (see the module docstring). Doesn't start anything - pass
    the result to `ophyd_async.tango.testing.start_tango_device_servers` (which
    is where you can override which interpreter actually hosts the servers).
    There's no per-call configuration: every device this ends up serving has a
    name fixed by `predict_trl`.

    :param prefix: The domain/family prefix every served device's name is
        built from, e.g. via `ophyd_async.tango.testing.generate_random_trl_prefix()`.
    """
    return [__file__, prefix]


def _wire_demo_devices(prefix: str) -> None:
    """Connect the channel/detector devices to their motors/channels.

    Done here, once, so `tango_device_servers_args` is genuinely
    standalone-runnable with no external orchestration required.
    """
    for channel_name in CHANNEL_NAMES:
        proxy = tango.DeviceProxy(predict_trl(prefix, channel_name))
        proxy.locator_x = predict_trl(prefix, MOTOR_X)
        proxy.locator_y = predict_trl(prefix, MOTOR_Y)
        proxy.connect_devices()
    detector_proxy = tango.DeviceProxy(predict_trl(prefix, DETECTOR))
    detector_proxy.locators = [predict_trl(prefix, name) for name in CHANNEL_NAMES]
    detector_proxy.connect_devices()


def _check_predicted_trl(ctx, prefix: str, device_name: str) -> None:
    """Canary check that predict_trl's assumptions still hold.

    If this ever fails, MultiDeviceTestContext's actual TRL shape has diverged
    from what predict_trl assumes - fail loudly here, at startup, rather than
    confusingly later when some other process tries to connect to a predicted
    TRL that was never actually being served.
    """
    actual = ctx.get_device_access(f"{prefix}/{device_name}")
    predicted = predict_trl(prefix, device_name)
    if actual != predicted:
        raise RuntimeError(f"Predicted TRL {predicted!r} doesn't match {actual!r}")


def _serve(prefix: str) -> None:
    """Serve the Demo*Device classes, blocking until stdin closes."""
    from tango.test_context import MultiDeviceTestContext

    motor_cls, detector_cls, channel_cls = _device_classes()

    port = _port_for_prefix(prefix)
    configs = [
        {
            "class": motor_cls,
            "devices": [
                {"name": f"{prefix}/{MOTOR_X}"},
                {"name": f"{prefix}/{MOTOR_Y}"},
            ],
        },
        {
            "class": channel_cls,
            "devices": [
                {"name": f"{prefix}/{name}", "properties": {"channel": i}}
                for i, name in enumerate(CHANNEL_NAMES, start=1)
            ],
        },
        {
            "class": detector_cls,
            "devices": [
                {
                    "name": f"{prefix}/{DETECTOR}",
                    "properties": {"channels": NUM_CHANNELS},
                }
            ],
        },
    ]
    with MultiDeviceTestContext(
        configs,
        host="127.0.0.1",
        port=port,
        process=False,
        timeout=30,
        green_mode=GreenMode.Asyncio,
    ) as ctx:
        _check_predicted_trl(ctx, prefix, DETECTOR)
        _wire_demo_devices(prefix)
        print(_READY_MARKER, flush=True)
        sys.stdin.readline()  # block until our parent closes our stdin


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <prefix>")
    _serve(sys.argv[1])
