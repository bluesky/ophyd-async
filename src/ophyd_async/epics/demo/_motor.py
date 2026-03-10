import asyncio
from dataclasses import dataclass
from functools import cached_property
from typing import Annotated as A

import numpy as np

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    MovableLogic,
    SignalR,
    SignalRW,
    SignalX,
    StandardMovable,
    StandardReadable,
    set_and_wait_for_other_value,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import EpicsDevice, PvSuffix


@dataclass
class DemoMotorMoveLogic(MovableLogic[float]):
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

    async def move(self, new_position: float, timeout: float | None) -> None:
        # If we are close to the desired position then break
        await set_and_wait_for_other_value(
            self.setpoint,
            new_position,
            self.readback,
            lambda v: bool(np.isclose(v, new_position)),
            timeout=timeout,
        )


class DemoMotor(EpicsDevice, StandardReadable, StandardMovable):
    """A demo movable that moves based on velocity."""

    # Define some signals
    readback: A[SignalR[float], PvSuffix("Readback"), Format.HINTED_SIGNAL]
    velocity: A[SignalRW[float], PvSuffix("Velocity"), Format.CONFIG_SIGNAL]
    units: A[SignalR[str], PvSuffix("Readback.EGU"), Format.CONFIG_SIGNAL]
    setpoint: A[SignalRW[float], PvSuffix("Setpoint")]
    precision: A[SignalR[int], PvSuffix("Readback.PREC")]
    # If a signal name clashes with a bluesky verb add _ to the attribute name
    stop_: A[SignalX, PvSuffix("Stop.PROC")]

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
