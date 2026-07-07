"""Tango device servers for the demo tutorial, and a launcher to run them up.

Kept as a single, self-contained module (not a package) so it stays trivially
importable/runnable on its own from a plain PyTango environment - it needs
`tango`/`tango.server` but nothing from `ophyd_async.tango.core` (the ophyd-async
client connection machinery), which the *ophyd-async* Devices in the rest of
`ophyd_async.tango.demo` (`DemoMotor`, `DemoStage`, ...) depend on instead.
"""

import asyncio
import atexit
import math
from enum import IntEnum

import tango
from tango import AttrWriteType, DevState, GreenMode
from tango.asyncio import DeviceProxy
from tango.server import Device, attribute, command, device_property

from ophyd_async.tango.testing import TangoSubprocessDeviceServer


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

    def init_device(self):
        super().init_device()
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


def start_device_server_subprocess(
    prefix: str, num_channels: int
) -> TangoSubprocessDeviceServer:
    """Start an IOC subprocess for sample stage and sensor.

    :param prefix: The prefix for the IOC PVs.
    :param num_channels: The number of point detector channels to create.
    """
    tango_server = TangoSubprocessDeviceServer(
        [
            {
                "class": DemoMotorDevice,
                "devices": [{"name": f"{prefix}/{suffix}"} for suffix in ["X", "Y"]],
            },
            {
                "class": DemoPointDetectorChannelDevice,
                "devices": [
                    {"name": f"{prefix}/C{channel}", "properties": {"channel": channel}}
                    for channel in range(1, num_channels + 1)
                ],
            },
            {
                "class": DemoMultiChannelDetectorDevice,
                "devices": [
                    {"name": f"{prefix}/DET", "properties": {"channels": num_channels}}
                ],
            },
        ]
    )
    tango_server.connect()

    channel_locators = []
    for channel in range(1, num_channels + 1):
        device_name = f"{prefix}/C{channel}"
        # Now connect the channel devices to the motor devices
        device_proxy = tango.DeviceProxy(tango_server.trls[device_name])
        device_proxy.locator_x = tango_server.trls[f"{prefix}/X"]
        device_proxy.locator_y = tango_server.trls[f"{prefix}/Y"]
        device_proxy.connect_devices()
        channel_locators.append(tango_server.trls[device_name])

    # Connect the Detector device to its individual channels
    device_proxy = tango.DeviceProxy(tango_server.trls[f"{prefix}/DET"])
    device_proxy.locators = channel_locators
    device_proxy.connect_devices()

    # Ensure the tango subprocess closes down and cleans up
    atexit.register(tango_server.disconnect)

    return tango_server
