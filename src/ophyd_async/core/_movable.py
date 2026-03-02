import asyncio
from abc import abstractmethod
from collections.abc import AsyncGenerator
from functools import cached_property
from typing import Generic

from bluesky.protocols import Locatable, Location, Reading, Stoppable, Subscribable

from ._device import Device, DeviceMock, default_mock_class
from ._mock_signal_utils import callback_on_mock_put, set_mock_value
from ._signal import SignalR, SignalRW, observe_value
from ._signal_backend import SignalDatatypeT
from ._status import AsyncStatus, WatchableAsyncStatus
from ._utils import (
    CALCULATE_TIMEOUT,
    CalculatableTimeout,
    Callback,
    WatcherUpdate,
)


class MovableLogic(Generic[SignalDatatypeT]):
    """Movable logic for stopping and checking valid moves of a StandardMovable."""

    setpoint: SignalRW[SignalDatatypeT]
    readback: SignalR[SignalDatatypeT]

    async def stop(self) -> None:
        """Optional hook to add logic on how to stop the motion."""
        return None

    async def check_move(
        self, old_position: SignalDatatypeT, new_position: SignalDatatypeT
    ) -> None:
        """Optional hook to check the move is valid."""
        return None

    async def calculate_timeout(
        self, old_position: SignalDatatypeT, new_position: SignalDatatypeT
    ) -> float | None:
        """Optional hook to calculate valid timeout for a move."""
        return None

    async def get_units_precision(self) -> tuple[str | None, int | None]:
        """Optional hook to return the units and precision."""
        return None, None

    def get_move_status(
        self, new_position: SignalDatatypeT, timeout: float | None
    ) -> AsyncStatus:
        return self.setpoint.set(new_position, timeout=timeout)

    async def move(
        self,
        move_status: AsyncStatus,
        old_position: SignalDatatypeT,
        new_position: SignalDatatypeT,
        timeout: float | None,
        units: str | None,
        precision: int | None,
    ) -> AsyncGenerator[WatcherUpdate[SignalDatatypeT], None]:

        async with move_status:
            async for current_position in observe_value(
                self.readback,
                done_status=move_status,
            ):
                yield WatcherUpdate[SignalDatatypeT](
                    current=current_position,
                    initial=old_position,
                    target=new_position,
                    name=self.readback.name,
                    unit=units,
                    precision=precision,
                )


class InstantMovableMock(DeviceMock["StandardMovable"]):
    """Mock behaviour that instantly moves readback to setpoint."""

    async def connect(self, device: "StandardMovable") -> None:
        """Mock signals to do an instant move on setpoint write."""

        def _instant_move(value):
            set_mock_value(device.movable_logic.readback, value)  # Arrive instantly

        callback_on_mock_put(device.movable_logic.setpoint, _instant_move)


@default_mock_class(InstantMovableMock)
class StandardMovable(
    Device,
    Locatable[SignalDatatypeT],
    Stoppable,
    Subscribable[SignalDatatypeT],
    Generic[SignalDatatypeT],
):
    """Device that provides standard logic for moving.

    This class must be inherited and have a ``movable_logic``property.
    """

    # Whether set() should complete successfully or not
    _set_success = True
    _move_status: AsyncStatus | None = None

    @cached_property
    @abstractmethod
    def movable_logic(self) -> MovableLogic:
        """Add movable logic for a device."""

    @WatchableAsyncStatus[SignalDatatypeT].wrap
    async def set(
        self,
        new_position: SignalDatatypeT,
        timeout: CalculatableTimeout = CALCULATE_TIMEOUT,
    ):
        """Move to the given value."""
        self._set_success = True
        old_position, (units, precision) = await asyncio.gather(
            self.movable_logic.readback.get_value(),
            self.movable_logic.get_units_precision(),
        )
        await self.movable_logic.check_move(old_position, new_position)

        calculate_timeout = await self.movable_logic.calculate_timeout(
            old_position, new_position
        )
        resolved_timeout: float | None = (
            calculate_timeout if timeout is CALCULATE_TIMEOUT else timeout
        )  # type: ignore
        try:
            self._move_status = self.movable_logic.get_move_status(
                new_position, timeout=resolved_timeout
            )
            if self._move_status is None:
                return
            async for update in self.movable_logic.move(
                move_status=self._move_status,
                old_position=old_position,
                new_position=new_position,
                timeout=resolved_timeout,
                units=units,
                precision=precision,
            ):
                if not self._set_success:
                    raise RuntimeError(f"Device {self.name} was stopped.")
                yield update
        finally:
            self._move_status = None

        if not self._set_success:
            raise RuntimeError(f"Device {self.name} was stopped.")

    async def stop(self, success=False):
        """Request to stop moving and return immediately."""
        self._set_success = success
        await self.movable_logic.stop()

    def set_name(self, name: str, *, child_name_separator: str | None = None) -> None:
        super().set_name(name, child_name_separator=child_name_separator)
        # Readback should be named the same as its parent in read()
        self.movable_logic.readback.set_name(name)

    async def locate(self) -> Location[SignalDatatypeT]:
        """Return the current setpoint and readback of the device."""
        setpoint, readback = await asyncio.gather(
            self.movable_logic.setpoint.get_value(),
            self.movable_logic.readback.get_value(),
        )
        return Location(setpoint=setpoint, readback=readback)

    def subscribe_reading(
        self, function: Callback[dict[str, Reading[SignalDatatypeT]]]
    ) -> None:
        """Subscribe to reading."""
        self.movable_logic.readback.subscribe_reading(function)

    subscribe = subscribe_reading

    def clear_sub(
        self, function: Callback[dict[str, Reading[SignalDatatypeT]]]
    ) -> None:
        """Unsubscribe."""
        self.movable_logic.readback.clear_sub(function)
