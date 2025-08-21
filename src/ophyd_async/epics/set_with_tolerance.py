"""A device that mimic a signal to allow a tolerance between set and readback."""

import asyncio

from bluesky.protocols import (
    Locatable,
    Location,
    Movable,
    Reading,
    Stoppable,
    Subscribable,
)

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    Callback,
    StandardReadable,
    WatchableAsyncStatus,
    WatcherUpdate,
    observe_value,
    set_and_wait_for_other_value,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import epics_signal_r, epics_signal_rw

__all__ = ["SetWithTolerance"]


class SetWithTolerance(
    StandardReadable,
    Locatable[float],
    Movable[float],
    Subscribable[float],
    Stoppable,
):
    """Tolerable Signal Device."""

    def __init__(
        self,
        setpoint_pv: str,
        readback_pv: str,
        tolerance: float = 0.01,
        name="",
    ):
        """Initialize the SetWithTolerance with default 0.01 tolerance.

        :param setpoint_pv: The PV for the setpoint.
        :param readback_pv: The PV  for the readback.
        :param name: The name of the device.
        """
        with self.add_children_as_readables(Format.HINTED_SIGNAL):
            self.user_readback = epics_signal_r(float, readback_pv)

        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.user_setpoint = epics_signal_rw(float, setpoint_pv)
            self.tolerance = soft_signal_rw(float, initial_value=tolerance)

        self._set_success = True
        self._stop = False
        super().__init__(name=name)

    @WatchableAsyncStatus.wrap
    async def set(
        self,
        value: float,
        timeout: float = DEFAULT_TIMEOUT,
        wait_for_set_completion: bool = True,
    ):
        """Set the device to a new position and wait until within tolerance.

        :param value: The target value to set.
        :param timeout: The maximum time to wait for the set operation to complete.
        :param wait_for_set_completion: If True, wait for the set signal to return true
            (Continue to wait even readback is within tolerance).
        """
        self._set_success = True
        old_position, tolerance = await asyncio.gather(
            self.user_readback.get_value(), self.tolerance.get_value()
        )
        move_status = self._set(
            value,
            tolerance=tolerance,
            timeout=timeout,
            wait_for_set_completion=wait_for_set_completion,
        )
        """keep watch on the readback value until it is within tolerance."""
        async for current_position in observe_value(
            self.user_readback, done_status=move_status
        ):
            yield WatcherUpdate(
                current=current_position,
                initial=old_position,
                target=value,
                name=self.name,
            )
        if not self._set_success:
            raise RuntimeError(f"Device '{self.name}' was stopped")

    async def locate(self) -> Location:
        """Return the setpoint and readback."""
        setpoint, readback = await asyncio.gather(
            self.user_setpoint.get_value(),
            self.user_readback.get_value(),
        )
        return Location(setpoint=setpoint, readback=readback)

    @AsyncStatus.wrap
    async def _set(
        self,
        new_position: float,
        tolerance: float,
        timeout,
        wait_for_set_completion: bool,
    ):
        """Set the device to a new position and wait until within tolerance."""

        def tolerable_condition(current_value: float) -> bool:
            """Condition to stop the set operation."""
            return abs(new_position - current_value) < abs(tolerance) or self._stop

        self._stop = False
        await set_and_wait_for_other_value(
            set_signal=self.user_setpoint,
            set_value=new_position,
            match_signal=self.user_readback,
            match_value=tolerable_condition,
            timeout=timeout,
            wait_for_set_completion=wait_for_set_completion,
        )

    async def stop(self, success: bool = False):
        """Stop the device by setting the setpoint to the current readback."""
        self._set_success = success
        self._stop = True
        await self.user_setpoint.set(await self.user_readback.get_value(), wait=False)

    def subscribe(self, function: Callback[dict[str, Reading[float]]]) -> None:
        """Subscribe."""
        self.user_readback.subscribe(function)

    def clear_sub(self, function: Callback[dict[str, Reading[float]]]) -> None:
        """Unsubscribe."""
        self.user_readback.clear_sub(function)
