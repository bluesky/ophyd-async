import asyncio
from collections.abc import Callable

from ophyd_async.core import simulate_move


class SimMotorHardware:
    """Simulated motor controller: plain asyncio, no ophyd-async.

    A move runs in its own task, passing each position to `set_readback` at 10Hz.

    :param position: where the motor starts.
    :param set_readback: called with each new position.
    :param set_setpoint: called with the position the motor stopped at by `stop`.
    :param set_done_move: called with 0 when a motion starts and 1 when it ends.
    :param velocity: speed of the constant velocity section, 0 means instant.
    :param acceleration_time: time taken to ramp up to (and down from) velocity.
    """

    def __init__(
        self,
        position: float,
        set_readback: Callable[[float], None],
        set_setpoint: Callable[[float], None],
        set_done_move: Callable[[int], None],
        velocity: float,
        acceleration_time: float,
    ):
        self.position = position
        self._velocity = velocity
        self._acceleration_time = acceleration_time
        self._set_readback = set_readback
        self._set_setpoint = set_setpoint
        self._set_done_move = set_done_move
        self._motion: asyncio.Task | None = None

    def set_velocity(self, velocity: float | None) -> None:
        """Set the speed of the constant velocity section, 0 means instant.

        `None` leaves it unchanged.
        """
        if velocity is not None:
            self._velocity = velocity

    def set_acceleration_time(self, acceleration_time: float | None) -> None:
        """Set the time taken to ramp up to (and down from) velocity.

        `None` leaves it unchanged.
        """
        if acceleration_time is not None:
            self._acceleration_time = acceleration_time

    async def move(self, target: float | None) -> float:
        """Stop any motion in progress, then move to `target`.

        Returns where the motor stopped, at `target` unless `stop` was called.

        :param target: where to move to, `None` for where it is now.
        """
        self.stop()
        await self.wait_until_stopped()
        if target is None:
            target = self.position
        self._set_done_move(0)
        self._motion = asyncio.create_task(self._simulate(target))
        self._motion.add_done_callback(lambda _: self._set_done_move(1))
        await asyncio.wait([self._motion])
        return self.position

    async def _simulate(self, target: float) -> None:
        moves = simulate_move(
            self.position, target, self._velocity, self._acceleration_time
        )
        async for position in moves:
            self.position = position
            self._set_readback(position)

    async def wait_until_stopped(self) -> None:
        """Wait until the motion in progress has finished or been stopped.

        Cancelling the wait leaves the motion running.
        """
        if self._motion is not None:
            await asyncio.wait([self._motion])

    def stop(self) -> None:
        """Stop the motion in progress where it is, like writing `.STOP`.

        The setpoint becomes the position it stopped at.
        """
        if self._motion is not None:
            self._motion.cancel()
        self._set_setpoint(self.position)
