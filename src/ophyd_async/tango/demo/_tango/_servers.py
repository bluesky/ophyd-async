import asyncio
import math
import time
from enum import IntEnum

import numpy as np
from tango import AttrWriteType, DevState, GreenMode
from tango.asyncio import DeviceProxy
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

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE, format="%6.3f")
    async def position(self):
        return self._position

    async def write_position(self, new_position):
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
        await self._move(self._setpoint)
        self.set_state(DevState.ON)

    async def _move(self, new_position):
        self._setpoint = new_position
        self._stop = False
        step = 0.1
        while True:
            if self._stop:
                self._stop = False
                break
            if abs(self._position - new_position) < abs(self._velocity * step):
                self._position = new_position
                break
            if self._position < new_position:
                self._position = self._position + self._velocity * step
            else:
                self._position = self._position - self._velocity * step
            await asyncio.sleep(step)


class Mode(IntEnum):
    LOW = 0
    HIGH = 1


class DemoMultiChannelDetectorDevice(Device):
    """Demo tango counting device."""

    channels = device_property(dtype=int, default_value=0)

    green_mode = GreenMode.Asyncio
    _locators = []
    _dps = []
    _acquire_time = 0.1
    _acquiring = False
    _elapsed = 0.0

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
            self._dps.append(await DeviceProxy(locator))

    @command
    async def start(self):
        await self._acquisition()
        # asyncio.create_task(self._acquisition())

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
        x: float = await self._dp_x.position  # type: ignore
        y: float = await self._dp_y.position  # type: ignore
        self._value = math.floor(
            (
                math.sin(x) ** self.channel
                + math.cos(x * y + self._energy_modes[self._mode])
                + 2
            )
            * 2500
            * self._elapsed
        )  # type: ignore

    @command
    async def connect_devices(self):
        # Connect by tango device proxy to the X motor
        self._dp_x = await DeviceProxy(self._locator_x)
        # Connect by tango device proxy to the Y motor
        self._dp_y = await DeviceProxy(self._locator_y)

    @attribute(dtype=int, access=AttrWriteType.READ)
    async def value(self):
        return self._value


class DemoCounterServer(Device):
    """Demo tango counting device."""

    green_mode = GreenMode.Asyncio
    _counts = 0
    _sample_time = 1.0

    @attribute(dtype=int, access=AttrWriteType.READ)
    async def counts(self):
        return self._counts

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE)
    async def sample_time(self):
        return self._sample_time

    async def write_sample_time(self, value: float):
        self._sample_time = value

    @attribute(dtype=DevState, access=AttrWriteType.READ)
    async def state(self):
        return self.get_state()

    @command
    async def reset(self):
        self._counts = 0
        return self._counts

    @command
    async def start(self):
        self._counts = 0
        if self._sample_time <= 0.0:
            return
        self.set_state(DevState.MOVING)
        await self._trigger()
        self.set_state(DevState.ON)

    async def _trigger(self):
        st = time.time()
        while True:
            ct = time.time()
            if ct - st > self._sample_time:
                break
            self._counts += int(np.random.normal(1000, 100))
            await asyncio.sleep(0.1)
