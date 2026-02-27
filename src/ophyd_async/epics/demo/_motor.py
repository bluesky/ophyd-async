import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    MovableLogic,
    SignalR,
    SignalRW,
    SignalX,
    StandardMovable,
    StandardReadable,
    StandardReadableFormat,
    WatcherUpdate,
    observe_value,
)
from ophyd_async.epics.core import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_x,
)


@dataclass
class DemoMotorMoveLogic(MovableLogic[float]):
    readback: SignalR[float]
    setpoint: SignalRW[float]
    velocity: SignalRW[float]
    units: SignalR[str]
    precision: SignalR[int]
    stop_: SignalX

    async def stop(self):
        await self.stop_.trigger()

    async def calculate_timeout(
        self, old_position: float, new_position: float
    ) -> float:
        velocity = await self.velocity.get_value()
        return abs(new_position - old_position) / velocity + DEFAULT_TIMEOUT

    async def get_units_precision(self) -> tuple[str, int]:
        return await asyncio.gather(
            self.units.get_value(),
            self.precision.get_value(),
        )

    async def move(
        self,
        move_status: AsyncStatus,
        old_position: float,
        new_position: float,
        timeout: float | None,
        units: str | None,
        precision: int | None,
    ) -> AsyncGenerator[WatcherUpdate[float], None]:

        await move_status

        # Observe the readback Signal, and on each new position...
        async for current_position in observe_value(
            self.readback, done_timeout=timeout
        ):
            # Emit a progress bar update
            yield WatcherUpdate(
                current=current_position,
                initial=old_position,
                target=new_position,
                name=self.readback.name,
                unit=units,
                precision=precision,
            )
            # If we are at the desired position the break
            if np.isclose(current_position, new_position):
                break


class DemoMotor(StandardReadable, StandardMovable):
    """A demo movable that moves based on velocity."""

    def __init__(self, prefix: str, name: str = ""):
        with self.add_children_as_readables(StandardReadableFormat.HINTED_SIGNAL):
            self.readback = epics_signal_r(float, prefix + "Readback")
        self.setpoint = epics_signal_rw(float, prefix + "Setpoint")

        with self.add_children_as_readables(StandardReadableFormat.CONFIG_SIGNAL):
            self.velocity = epics_signal_rw(float, prefix + "Velocity")
            self.units = epics_signal_r(str, prefix + "Readback.EGU")

        self.precision = epics_signal_r(int, prefix + "Readback.PREC")
        # If a signal name clashes with a bluesky verb add _ to the attribute name
        self.stop_ = epics_signal_x(prefix + "Stop.PROC")

        super().__init__(name)

    @cached_property
    def movable_logic(self) -> DemoMotorMoveLogic:
        return DemoMotorMoveLogic(
            readback=self.readback,
            setpoint=self.setpoint,
            velocity=self.velocity,
            units=self.units,
            precision=self.precision,
            stop_=self.stop_,
        )
