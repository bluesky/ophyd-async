import asyncio

import numpy as np
from bluesky.protocols import Movable, Stoppable

from ophyd_async.core import (
    CALCULATE_TIMEOUT,
    DEFAULT_TIMEOUT,
    AsyncStatus,
    CalculatableTimeout,
    ConfigSignal,
    Device,
    HintedSignal,
    StandardReadable,
    WatchableAsyncStatus,
    WatcherUpdate,
    observe_value,
)
from ophyd_async.epics.signal import epics_signal_r, epics_signal_rw, epics_signal_x


class Mover(StandardReadable, Movable, Stoppable):
    """A demo movable that moves based on velocity"""

    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        with self.add_children_as_readables(HintedSignal):
            self.readback = epics_signal_r(float, prefix + "Readback")
        with self.add_children_as_readables(ConfigSignal):
            self.velocity = epics_signal_rw(float, prefix + "Velocity")
            self.units = epics_signal_r(str, prefix + "Readback.EGU")
        self.setpoint = epics_signal_rw(float, prefix + "Setpoint")
        self.precision = epics_signal_r(int, prefix + "Readback.PREC")
        # Signals that collide with standard methods should have a trailing underscore
        self.stop_ = epics_signal_x(prefix + "Stop.PROC")
        # Whether set() should complete successfully or not
        self._set_success = True

        super().__init__(name=name)

    def set_name(self, name: str):
        super().set_name(name)
        # Readback should be named the same as its parent in read()
        self.readback.set_name(name)

    @WatchableAsyncStatus.wrap
    async def set(self, value: float, timeout: CalculatableTimeout = CALCULATE_TIMEOUT):
        new_position = value
        self._set_success = True
        old_position, units, precision, velocity = await asyncio.gather(
            self.setpoint.get_value(),
            self.units.get_value(),
            self.precision.get_value(),
            self.velocity.get_value(),
        )
        if timeout == CALCULATE_TIMEOUT:
            assert velocity > 0, "Mover has zero velocity"
            timeout = abs(new_position - old_position) / velocity + DEFAULT_TIMEOUT
        # Make an Event that will be set on completion, and a Status that will
        # error if not done in time
        done = asyncio.Event()
        done_status = AsyncStatus(asyncio.wait_for(done.wait(), timeout))
        # Wait for the value to set, but don't wait for put completion callback
        await self.setpoint.set(new_position, wait=False)
        async for current_position in observe_value(
            self.readback, done_status=done_status
        ):
            yield WatcherUpdate(
                current=current_position,
                initial=old_position,
                target=new_position,
                name=self.name,
                unit=units,
                precision=precision,
            )
            if np.isclose(current_position, new_position):
                done.set()
                break
        if not self._set_success:
            raise RuntimeError("Motor was stopped")

    async def stop(self, success=True):
        self._set_success = success
        status = self.stop_.trigger()
        await status


class SampleStage(Device):
    """A demo sample stage with X and Y movables"""

    def __init__(self, prefix: str, name="") -> None:
        # Define some child Devices
        self.x = Mover(prefix + "X:")
        self.y = Mover(prefix + "Y:")
        # Set name of device and child devices
        super().__init__(name=name)
