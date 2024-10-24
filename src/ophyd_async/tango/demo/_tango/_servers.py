import asyncio
import time

import numpy as np

from tango import AttrWriteType, DevState, GreenMode
from tango.server import Device, attribute, command


class DemoMover(Device):
    green_mode = GreenMode.Asyncio
    _position = 0.0
    _setpoint = 0.0
    _velocity = 0.5
    _acceleration = 0.5
    _precision = 0.1
    _stop = False
    DEVICE_CLASS_INITIAL_STATE = DevState.ON

    @attribute(dtype=float, access=AttrWriteType.READ_WRITE)
    async def position(self):
        return self._position

    async def write_position(self, new_position):
        self._setpoint = new_position
        await self.move()

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
            if self._position < new_position:
                self._position = self._position + self._velocity * step
            else:
                self._position = self._position - self._velocity * step
            if abs(self._position - new_position) < self._precision:
                self._position = new_position
                break
            await asyncio.sleep(step)


class DemoCounter(Device):
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
