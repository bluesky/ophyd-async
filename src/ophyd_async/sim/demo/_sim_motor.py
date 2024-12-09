import asyncio
import contextlib
import time

import numpy as np
from bluesky.protocols import Movable, Stoppable

from ophyd_async.core import (
    AsyncStatus,
    StandardReadable,
    WatchableAsyncStatus,
    WatcherUpdate,
    observe_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format


class SimMotor(StandardReadable, Movable, Stoppable):
    def __init__(self, name="", instant=True) -> None:
        """
        Simulated motor device

        args:
        - prefix: str: Signal names prefix
        - name: str: name of device
        - instant: bool: whether to move instantly, or with a delay
        """
        # Define some signals
        with self.add_children_as_readables(Format.HINTED_SIGNAL):
            self.user_readback, self._user_readback_set = soft_signal_r_and_setter(
                float, 0
            )
        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.velocity = soft_signal_rw(float, 0 if instant else 1.0)
            self.units = soft_signal_rw(str, "mm")
        self.user_setpoint = soft_signal_rw(float, 0)

        # Whether set() should complete successfully or not
        self._set_success = True
        self._move_status: AsyncStatus | None = None

        super().__init__(name=name)

    async def _move(self, old_position: float, new_position: float, move_time: float):
        start = time.monotonic()
        # Make an array of relative update times at 10Hz intervals
        update_times = np.arange(0.1, move_time, 0.1)
        # With the end position appended
        update_times = np.concatenate((update_times, [move_time]))
        # Interpolate the [old, new] position array with those update times
        new_positions = np.interp(
            update_times, [0, move_time], [old_position, new_position]
        )
        for update_time, new_position in zip(update_times, new_positions, strict=True):
            # Calculate how long to wait to get there
            relative_time = time.monotonic() - start
            await asyncio.sleep(update_time - relative_time)
            # Update the readback position
            self._user_readback_set(new_position)

    @WatchableAsyncStatus.wrap
    async def set(self, value: float):
        """
        Asynchronously move the motor to a new position.
        """
        new_position = value
        # Make sure any existing move tasks are stopped
        await self.stop()
        old_position, units, velocity = await asyncio.gather(
            self.user_setpoint.get_value(),
            self.units.get_value(),
            self.velocity.get_value(),
        )
        # If zero velocity, do instant move
        if velocity == 0:
            self._user_readback_set(new_position)
        else:
            move_time = abs(new_position - old_position) / velocity
            self._move_status = AsyncStatus(
                self._move(old_position, new_position, move_time)
            )
            # If stop is called then this will raise a CancelledError, ignore it
            with contextlib.suppress(asyncio.CancelledError):
                async for current_position in observe_value(
                    self.user_readback, done_status=self._move_status
                ):
                    yield WatcherUpdate(
                        current=current_position,
                        initial=old_position,
                        target=new_position,
                        name=self.name,
                        unit=units,
                    )
        if not self._set_success:
            raise RuntimeError("Motor was stopped")

    async def stop(self, success=True):
        """
        Stop the motor if it is moving
        """
        self._set_success = success
        if self._move_status:
            self._move_status.task.cancel()
            self._move_status = None
        await self.user_setpoint.set(await self.user_readback.get_value())
