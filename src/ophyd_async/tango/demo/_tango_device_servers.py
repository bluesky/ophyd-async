"""Run the Tango device servers backing the `ophyd_async.tango.demo` tutorial.

Genuinely standalone: nothing in this file imports anything from `ophyd_async`
- only `tango`/`tango.server` and stdlib. That's deliberate, not incidental: it
means this file can be copied into (or run from) a separate PyTango-only venv
that doesn't have `ophyd_async` installed at all, exactly as a real `softIoc`
binary doesn't need whatever's launching it to be Python.

Takes a prefix, a port, and a channel count on the command line, like any
other Tango device server would - nothing is ever read back about what got
served or which port it ended up on, because you already said. Run directly
with a plain PyTango interpreter, by file path:

    tango-venv/bin/python \
        /path/to/ophyd_async/tango/demo/_tango_device_servers.py test/abc 12345 3

It prints a readiness marker once serving, then blocks until stdin closes (or
EOFs), at which point it exits. See `ophyd_async.tango.testing.
start_tango_device_servers` for how ophyd_async client code launches this as
a managed subprocess.

Serves `DemoMotorDevice`/`DemoMultiChannelDetectorDevice`/
`DemoPointDetectorChannelDevice` (below), which all need `GreenMode.Asyncio` for
their `asyncio.sleep`-based movement/acquisition simulation - a separate
module/process from `ophyd_async.tango.testing`'s test-only device servers
(which use the default sync green mode - PyTango only allows one green mode
per device server process).

- `DemoMotorDevice`: backs `DemoMotor`/`DemoStage`.
- `DemoMultiChannelDetectorDevice`/`DemoPointDetectorChannelDevice`: back
  `DemoPointDetector`/`DemoPointDetectorChannel`.
"""

import argparse
import asyncio
import math
import sys
from enum import IntEnum

import tango
from tango import AttrWriteType, DevState, GreenMode
from tango.asyncio import DeviceProxy
from tango.server import Device, attribute, command, device_property
from tango.test_context import MultiDeviceTestContext

_READY_MARKER = "TANGO_DEVICE_SERVERS_READY"


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

    # PyTango's stubs type Device.init_device as sync-only, but under
    # GreenMode.Asyncio (this class) an async override is the documented,
    # correct pattern - pyright just can't see that.
    async def init_device(self):  # pyright: ignore[reportIncompatibleMethodOverride]
        await super().init_device()  # pyright: ignore[reportGeneralTypeIssues]
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


def _trl(prefix: str, port: int, device_name: str) -> str:
    """Build the TRL this process serves `device_name` at.

    Only used internally, to cross-wire the channel/detector devices to
    their motors/channels below - callers outside this process build TRLs
    the same way independently (see `ophyd_async.tango.testing.trl`).
    """
    return f"tango://127.0.0.1:{port}/{prefix}/{device_name}#dbase=no"


def _wire_demo_devices(prefix: str, port: int, channel_names: list[str]) -> None:
    """Connect the channel/detector devices to their motors/channels."""
    for name in channel_names:
        proxy = tango.DeviceProxy(_trl(prefix, port, name))
        proxy.locator_x = _trl(prefix, port, "motor-x")
        proxy.locator_y = _trl(prefix, port, "motor-y")
        proxy.connect_devices()
    detector_proxy = tango.DeviceProxy(_trl(prefix, port, "detector"))
    detector_proxy.locators = [_trl(prefix, port, name) for name in channel_names]
    detector_proxy.connect_devices()


def _serve(prefix: str, port: int, num_channels: int) -> None:
    """Serve the Demo*Device classes, blocking until stdin closes."""
    channel_names = [f"channel-{i}" for i in range(1, num_channels + 1)]
    configs = [
        {
            "class": DemoMotorDevice,
            "devices": [
                {"name": f"{prefix}/motor-x"},
                {"name": f"{prefix}/motor-y"},
            ],
        },
        {
            "class": DemoPointDetectorChannelDevice,
            "devices": [
                {"name": f"{prefix}/{name}", "properties": {"channel": i}}
                for i, name in enumerate(channel_names, start=1)
            ],
        },
        {
            "class": DemoMultiChannelDetectorDevice,
            "devices": [
                {
                    "name": f"{prefix}/detector",
                    "properties": {"channels": num_channels},
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
    ):
        _wire_demo_devices(prefix, port, channel_names)
        print(_READY_MARKER, flush=True)
        sys.stdin.readline()  # block until our parent closes our stdin


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Serve the demo motor/channel/detector Tango device catalog."
    )
    parser.add_argument("prefix", help="Domain/family prefix for served device names")
    parser.add_argument("port", type=int, help="TCP port to listen on")
    parser.add_argument(
        "num_channels", type=int, help="Number of point-detector channels to serve"
    )
    args = parser.parse_args()
    _serve(args.prefix, args.port, args.num_channels)
