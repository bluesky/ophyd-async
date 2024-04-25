import asyncio
import time
from typing import Callable, List, Optional

from bluesky.protocols import Movable, Stoppable

from ophyd_async.core import StandardReadable
from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.signal import soft_signal_r_and_backend, soft_signal_rw
from ophyd_async.core.standard_readable import ConfigSignal, HintedSignal


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
            self.user_readback, self._user_readback = soft_signal_r_and_backend(
                float, 0
            )

        with self.add_children_as_readables(ConfigSignal):
            self.velocity = soft_signal_rw(float, 1.0)
            self.egu = soft_signal_rw(float, "mm")

        self._instant = instant
        self._move_task: Optional[asyncio.Task] = None

        # Define some signals
        self.user_setpoint = soft_signal_rw(float, 0)

        super().__init__(name=name)

        # Whether set() should complete successfully or not
        self._set_success = True

    def stop(self, success=False):
        """
        Stop the motor if it is moving
        """
        if self._move_task:
            self._move_task.cancel()
            self._move_task = None

        self._set_success = success

    def set(self, new_position: float, timeout: Optional[float] = None) -> AsyncStatus:  # noqa: F821
        """
        Asynchronously move the motor to a new position.
        """
        watchers: List[Callable] = []
        coro = asyncio.wait_for(self._move(new_position, watchers), timeout=timeout)
        return AsyncStatus(coro, watchers)

    async def _move(self, new_position: float, watchers: List[Callable] = []):
        """
        Start the motor moving to a new position.

        If the motor is already moving, it will stop first.
        If this is an instant motor the move will be instantaneous.
        """
        self.stop()
        start = time.monotonic()

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
                    await self._user_readback.put(new_position)
                    self._set_success = True
                    break
                else:
                    current_position = (
                        old_position + distance * time_elapsed / travel_time
                    )

                await self._user_readback.put(current_position)

                # notify watchers of the new position
                for watcher in watchers:
                    watcher(
                        name=self.name,
                        current=current_position,
                        initial=old_position,
                        target=new_position,
                        unit=units,
                        time_elapsed=time.monotonic() - start,
                    )

                # 10hz update loop
                await asyncio.sleep(0.1)

        # set up a task that updates the motor position at 10hz
        self._move_task = asyncio.create_task(update_position())

        try:
            await self._move_task
        finally:
            if not self._set_success:
                raise RuntimeError("Motor was stopped")
