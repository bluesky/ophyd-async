from dataclasses import dataclass
from functools import cached_property
from typing import Annotated as A

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    CalculatedTimeout,
    MovableLogic,
    SignalR,
    SignalRW,
    StandardMovable,
    StandardReadable,
    TriggerableCommand,
    wait_for_value,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.tango.core import DevStateEnum, TangoDevice, TangoPolling


@dataclass
class DemoMotorMoveLogic(MovableLogic[float]):
    velocity: SignalRW[float]
    stop_: TriggerableCommand
    state: SignalR[DevStateEnum]

    async def stop(self):
        await self.stop_.trigger()

    async def calculate_timeout(
        self, old_position: float, new_position: float
    ) -> float:
        velocity = await self.velocity.get_value()
        return abs(new_position - old_position) / velocity + DEFAULT_TIMEOUT

    async def move(self, new_position: float, timeout: CalculatedTimeout) -> None:
        # Write the setpoint and wait for the motor state to return to ON,
        # which happens whether the move completes normally or is stopped.
        await self.setpoint.set(new_position, timeout=timeout())
        await wait_for_value(self.state, DevStateEnum.ON, timeout=timeout())


class DemoMotor(TangoDevice, StandardReadable, StandardMovable[float]):
    """A demo movable that moves based on velocity."""

    # If the server doesn't support events, the TangoPolling annotation gives
    # the parameters for ophyd to poll instead
    readback: A[SignalR[float], TangoPolling(0.1, 0.001, 0.001), Format.HINTED_SIGNAL]
    velocity: A[SignalRW[float], TangoPolling(0.1, 0.001, 0.001), Format.CONFIG_SIGNAL]
    setpoint: A[SignalRW[float], TangoPolling(0.1, 0.001, 0.001)]
    state: A[SignalR[DevStateEnum], TangoPolling(0.1)]
    # If a tango name clashes with a bluesky verb, add a trailing underscore
    stop_: TriggerableCommand

    @cached_property
    def movable_logic(self) -> MovableLogic:
        return DemoMotorMoveLogic(
            readback=self.readback,
            setpoint=self.setpoint,
            velocity=self.velocity,
            stop_=self.stop_,
            state=self.state,
        )
