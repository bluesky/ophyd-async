import asyncio
import time
from dataclasses import replace

from bluesky.protocols import Movable, Stoppable

from ophyd_async.core import StandardReadable
from ophyd_async.core.async_status import AsyncStatus, WatchableAsyncStatus
from ophyd_async.core.signal import (
    observe_value,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core.standard_readable import ConfigSignal, HintedSignal
from ophyd_async.core.utils import WatcherUpdate


class SimMotor(StandardReadable, Movable, Stoppable):
    def __init__(self, name="", instant=True) -> None:
        """
        Simulated motor device

        args:
        - prefix: str: Signal names prefix
        - name: str: name of device
        - instant: bool: whether to move instantly, or with a delay
        """
        with self.add_children_as_readables(HintedSignal):
            self.user_readback, self._user_readback_set = soft_signal_r_and_setter(
                float, 0
            )

        with self.add_children_as_readables(ConfigSignal):
            self.velocity = soft_signal_rw(float, 1.0)
            self.egu = soft_signal_rw(str, "mm")

        self._instant = instant
        self._move_status: AsyncStatus | None = None

        # Define some signals
        self.user_setpoint = soft_signal_rw(float, 0)

        super().__init__(name=name)

        # Whether set() should complete successfully or not
        self._set_success = True

    def stop(self, success=False):
        """
        Stop the motor if it is moving
        """
        if self._move_status:
            self._move_status.task.cancel()
            self._move_status = None

        async def trigger_callbacks():
            await self.user_readback._backend.put(
                await self.user_readback._backend.get_value()
            )

        asyncio.create_task(trigger_callbacks())

        self._set_success = success

    @WatchableAsyncStatus.wrap
    async def set(self, new_position: float, timeout: float | None = None):
        """
        Asynchronously move the motor to a new position.
        """
        update, move_status = await self._move(new_position, timeout)
        async for current_position in observe_value(
            self.user_readback, done_status=move_status
        ):
            if not self._set_success:
                raise RuntimeError("Motor was stopped")
            yield replace(
                update,
                name=self.name,
                current=current_position,
            )

    async def _move(self, new_position: float, timeout: float | None = None):
        """
        Start the motor moving to a new position.

        If the motor is already moving, it will stop first.
        If this is an instant motor the move will be instantaneous.
        """
        self.stop()
        start = time.monotonic()
        self._set_success = True

        current_position = await self.user_readback.get_value()
        distance = abs(new_position - current_position)
        travel_time = 0 if self._instant else distance / await self.velocity.get_value()

        old_position, units = await asyncio.gather(
            self.user_setpoint.get_value(),
            self.egu.get_value(),
        )

        async def update_position():
            while True:
                time_elapsed = round(time.monotonic() - start, 2)

                # update position based on time elapsed
                if time_elapsed >= travel_time:
                    # successfully reached our target position
                    self._user_readback_set(new_position)
                    self._set_success = True
                    break
                else:
                    current_position = (
                        old_position + distance * time_elapsed / travel_time
                    )

                self._user_readback_set(current_position)

                # 10hz update loop
                await asyncio.sleep(0.1)

        # set up a task that updates the motor position at ~10hz
        self._move_status = AsyncStatus(asyncio.wait_for(update_position(), timeout))

        return (
            WatcherUpdate(
                initial=old_position,
                current=old_position,
                target=new_position,
                unit=units,
            ),
            self._move_status,
        )
