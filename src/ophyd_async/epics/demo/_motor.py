import asyncio
from typing import Annotated as A

import numpy as np
from bluesky.protocols import Movable, Stoppable

from ophyd_async.core import (
    CALCULATE_TIMEOUT,
    DEFAULT_TIMEOUT,
    CalculatableTimeout,
    SignalR,
    SignalRW,
    SignalX,
    StandardReadable,
    WatchableAsyncStatus,
    WatcherUpdate,
    observe_value,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import EpicsDevice, PvSuffix


class DemoMotor(EpicsDevice, StandardReadable, Movable, Stoppable):
    """A demo movable that moves based on velocity."""

    # Whether set() should complete successfully or not
    _set_success = True
    # Define some signals
    readback: A[SignalR[float], PvSuffix("Readback"), Format.HINTED_SIGNAL]
    velocity: A[SignalRW[float], PvSuffix("Velocity"), Format.CONFIG_SIGNAL]
    units: A[SignalR[str], PvSuffix("Readback.EGU"), Format.CONFIG_SIGNAL]
    setpoint: A[SignalRW[float], PvSuffix("Setpoint")]
    precision: A[SignalR[int], PvSuffix("Readback.PREC")]
    # If a signal name clashes with a bluesky verb add _ to the attribute name
    stop_: A[SignalX, PvSuffix("Stop.PROC")]

    def set_name(self, name: str, *, child_name_separator: str | None = None) -> None:
        super().set_name(name, child_name_separator=child_name_separator)
        # Readback should be named the same as its parent in read()
        self.readback.set_name(name)

    @WatchableAsyncStatus.wrap
    async def set(  # type: ignore
        self, new_position: float, timeout: CalculatableTimeout = CALCULATE_TIMEOUT
    ):
        # The move should complete successfully unless stop(success=False) is called
        self._set_success = True
        # Get some variables for the progress bar reporting
        old_position, units, precision, velocity = await asyncio.gather(
            self.setpoint.get_value(),
            self.units.get_value(),
            self.precision.get_value(),
            self.velocity.get_value(),
        )
        # If not supplied, calculate a suitable timeout for the move
        if timeout == CALCULATE_TIMEOUT:
            timeout = abs(new_position - old_position) / velocity + DEFAULT_TIMEOUT
        # Wait for the value to set, but don't wait for put completion callback
        await self.setpoint.set(new_position, wait=False)
        # Observe the readback Signal, and on each new position...
        async for current_position in observe_value(
            self.readback, done_timeout=timeout
        ):
            # Emit a progress bar update
            yield WatcherUpdate(
                current=current_position,
                initial=old_position,
                target=new_position,
                name=self.name,
                unit=units,
                precision=precision,
            )
            # If we are at the desired position the break
            if np.isclose(current_position, new_position):
                break
        # If we were told to stop and report an error then do so
        if not self._set_success:
            raise RuntimeError("Motor was stopped")

    async def stop(self, success=True):
        self._set_success = success
        await self.stop_.trigger()
