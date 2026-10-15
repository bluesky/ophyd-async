"""A device that mimics a signal to allow a tolerance between setpoint and readback."""

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
    derived_signal_r,
    observe_value,
    set_and_wait_for_other_value,
    soft_signal_r_and_setter,
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
    """SetWithTolerance allowing a tolerance between setpoint and readback."""

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
        :param tolerance: Allowed tolerance between setpoint and readback.
        :param name: The name of the device.
        """
        with self.add_children_as_readables(Format.HINTED_SIGNAL):
            self.user_readback = epics_signal_r(float, readback_pv)

        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.user_setpoint = epics_signal_rw(float, setpoint_pv)
            self.tolerance = soft_signal_rw(float, initial_value=tolerance)
            self._timeout, self._timeout_setter = soft_signal_r_and_setter(
                float, initial_value=DEFAULT_TIMEOUT
            )
        self.within_tolerance = derived_signal_r(
            raw_to_derived=self._within_tolerance,
            setpoint=self.user_setpoint,
            readback=self.user_readback,
            tolerance=self.tolerance,
        )
        self._set_success = True
        super().__init__(name=name)

    def _within_tolerance(
        self, setpoint: float, readback: float, tolerance: float
    ) -> bool:
        """Check if the readback is within the tolerance of the setpoint."""
        return abs(setpoint - readback) < abs(tolerance)

    @WatchableAsyncStatus.wrap
    async def set(
        self,
        value: float,
        timeout: float | None = None,
    ):
        """Set the device to a new position and wait until within tolerance.

        :param value: The target value to set.
        :param timeout: The maximum time to wait for the set operation to complete.
        """
        await self.stop(success=True)  # Stop previous set and mark them as success.
        if timeout is None:
            timeout = await self._timeout.get_value()
        else:
            self._timeout_setter(timeout)
        old_position = await self.user_readback.get_value()
        # Preset setpoint as set_and_wait_for_other_value does first check before set.
        await self.user_setpoint.set(value, False)
        move_status = AsyncStatus(
            set_and_wait_for_other_value(
                set_signal=self.user_setpoint,
                set_value=value,
                match_signal=self.within_tolerance,
                match_value=True,
                timeout=timeout,
            )
        )

        # Keep watch on the readback value until it is within tolerance.
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

    async def stop(self, success: bool = False):
        """Stop the device by setting the setpoint to the current readback."""
        self._set_success = success
        await self.user_setpoint.set(await self.user_readback.get_value())

    def subscribe(self, function: Callback[dict[str, Reading[float]]]) -> None:
        """Subscribe."""
        self.user_readback.subscribe(function)

    def clear_sub(self, function: Callback[dict[str, Reading[float]]]) -> None:
        """Unsubscribe."""
        self.user_readback.clear_sub(function)

    def set_name(self, name: str, *, child_name_separator: str | None = None) -> None:
        """Set name of the motor and its children."""
        super().set_name(name, child_name_separator=child_name_separator)
        # SetPoint and Readback should be named the same as its parent in read()
        self.user_readback.set_name(name)
