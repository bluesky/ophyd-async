import asyncio
import time
from typing import Callable, List, Optional

from bluesky.protocols import Movable, Stoppable
from ophyd_async.core import StandardReadable, set_sim_value
from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.signal import soft_signal_r_and_backend, soft_signal_rw


class SimMotor(StandardReadable, Movable, Stoppable):
    def __init__(self, prefix: str, name="", instant=True) -> None:
        """
        Simulated motor device

        args:
        - prefix: str: Signal names prefix
        - name: str: name of device
        - instant: bool: whether to move instantly, or with a delay
        """
        self._instant = instant
        self._move_task: Optional[asyncio.Task] = None

        # Define some signals
        self.user_setpoint = soft_signal_rw(
            float, "user_setpoint", prefix + ".setpoint"
        )
        self.user_readback, self._user_readback = soft_signal_r_and_backend(
            float, "user_readback", prefix + ".readback"
        )
        self.velocity = soft_signal_rw(float, "velocity", prefix + ".velocity")
        self.egu = soft_signal_rw(float, "egu", prefix + ".egu")

        # sensible defaults
        self.velocity.set(1)
        self.egu.set("mm")

        # Set name and signals for read() and read_configuration()
        self.set_readable_signals(
            read=[self.user_readback],
            config=[self.velocity, self.egu],
        )
        super().__init__(name=name)

        # Whether set() should complete successfully or not
        self._set_success = True

    def stop(self):
        """
        Stop the motor if it is moving
        """
        if self._move_task:
            self._move_task.cancel()
            self._move_task = None

    def move(self, new_position: float, timeout: Optional[float] = None):
        """
        Commandline only synchronous move of a Motor
        """
        from bluesky.run_engine import call_in_bluesky_event_loop, in_bluesky_event_loop

        if in_bluesky_event_loop():
            raise RuntimeError("Will deadlock run engine if run in a plan")
        call_in_bluesky_event_loop(self._move(new_position), timeout)  # type: ignore

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

        If the motor is already moving, it will stop and start moving to the
        new position.
        If this is an instant motor the move will be instantaneous.
        """
        self.stop()
        self._set_success = True
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
                if time_elapsed >= travel_time:
                    current_position = new_position
                    break
                else:
                    current_position = (
                        old_position + distance * time_elapsed / travel_time
                    )

                await self._user_readback.put(current_position)
                await asyncio.sleep(0.1)

        def update_watchers(current_position: float):
            for watcher in watchers:
                watcher(
                    name=self.name,
                    current=current_position,
                    initial=old_position,
                    target=new_position,
                    unit=units,
                    time_elapsed=time.monotonic() - start,
                )

        # set up a task that updates the motor position at 10hz
        self._move_task = asyncio.create_task(update_position())

        # set up watchers to be called when the motor position changes
        self.user_readback.subscribe_value(update_watchers)
