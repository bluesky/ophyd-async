"""A device that mimic a signal to allow tolerance."""

import asyncio
from typing import TypeVar

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

T = TypeVar("T")


class TolerableDevice(
    StandardReadable,
    Locatable[float | int],
    Movable[float | int],
    Subscribable[float | int],
    Stoppable,
):
    """Tolerable Signal Device."""

    def __init__(
        self,
        setpoint_pv: str,
        readback_pv: str,
        Signal_data_type: type[float | int],
        name="",
    ):
        with self.add_children_as_readables(Format.HINTED_SIGNAL):
            self.user_readback = epics_signal_r(Signal_data_type, readback_pv)

        with self.add_children_as_readables(Format.CONFIG_SIGNAL):
            self.user_setpoint = epics_signal_rw(Signal_data_type, setpoint_pv)
            self.tolerance = soft_signal_rw(Signal_data_type)

        # Whether set() should complete successfully or not
        self._set_success = True
        super().__init__(name=name)

    @WatchableAsyncStatus.wrap
    async def set(self, value: float | int, timeout: float = DEFAULT_TIMEOUT):
        """Set signal and wait until it is within tolerance."""
        self._set_success = True
        tolerance = await self.tolerance.get_value()
        old_position, tolerance = await asyncio.gather(
            self.user_readback.get_value(), self.tolerance.get_value()
        )

        move_status = await set_and_wait_for_other_value(
            set_signal=self.user_setpoint,
            set_value=value,
            match_signal=self.user_readback,
            match_value=lambda current_value: abs(value - current_value) < tolerance,
            timeout=timeout,
        )

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
            raise RuntimeError("Device was stopped")

    async def locate(self) -> Location:
        """Return the setpoint and readback."""
        setpoint, readback = await asyncio.gather(
            self.user_setpoint.get_value(),
            self.user_readback.get_value(),
        )
        return Location(setpoint=setpoint, readback=readback)

    async def stop(self, success=False):
        """Mimic a stop by setting the set point to readback."""
        self._set_success = success
        await self.user_setpoint.set(await self.user_readback.get_value(), wait=False)

    def subscribe(self, function: Callback[dict[str, Reading[float | int]]]) -> None:
        """Subscribe."""
        self.user_readback.subscribe(function)

    def clear_sub(self, function: Callback[dict[str, Reading[float | int]]]) -> None:
        """Unsubscribe."""
        self.user_readback.clear_sub(function)
