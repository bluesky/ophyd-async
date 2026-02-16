import asyncio
from abc import ABC, abstractmethod

from bluesky.protocols import Locatable, Location, Reading, Stoppable, Subscribable

from ._device import Device
from ._signal import SignalR, SignalRW, observe_value
from ._status import WatchableAsyncStatus
from ._utils import (
    CALCULATE_TIMEOUT,
    CalculatableTimeout,
    Callback,
    WatcherUpdate,
    error_if_none,
)


class MovableLogic(ABC):
    setpoint_signal: SignalRW[float]
    readback_signal: SignalR[float]

    @abstractmethod
    async def stop(self):
        """Stop the motion."""

    @abstractmethod
    async def check_move(self, old_position: float, new_position: float) -> None:
        """Check the move is valid and return the timeout."""

    @abstractmethod
    async def calculate_timeout(
        self, old_position: float, new_position: float
    ) -> float:
        """Check the move is valid and return the timeout."""

    @abstractmethod
    async def get_units_precision(self) -> tuple[str | None, int | None]:
        """Return the units and precision."""


class StandardMovable(Device, Locatable[float], Stoppable, Subscribable):
    # Whether set() should complete successfully or not
    _set_success = True
    __movable_logic: MovableLogic | None = None

    def add_movable_logic(self, logic: MovableLogic):
        if self.__movable_logic is not None:
            raise RuntimeError("Device already has movable logic")
        self.__movable_logic = logic

    @property
    def _movable_logic(self) -> MovableLogic:
        return error_if_none(self.__movable_logic, "Movable logic not added.")

    def set_name(self, name: str, *, child_name_separator: str | None = None) -> None:
        super().set_name(name, child_name_separator=child_name_separator)
        # Readback should be named the same as its parent in read()
        self._movable_logic.readback_signal.set_name(name)

    @WatchableAsyncStatus.wrap
    async def set(
        self, new_position: float, timeout: CalculatableTimeout = CALCULATE_TIMEOUT
    ):
        """Move motor to the given value."""
        self._set_success = True
        old_position, (units, precision) = await asyncio.gather(
            self._movable_logic.setpoint_signal.get_value(),
            self._movable_logic.get_units_precision(),
        )
        await self._movable_logic.check_move(old_position, new_position)
        calculated_timeout = await self._movable_logic.calculate_timeout(
            old_position, new_position
        )

        async with self._movable_logic.setpoint_signal.set(
            new_position,
            timeout=calculated_timeout if timeout is CALCULATE_TIMEOUT else timeout,
        ):
            async for current_position in observe_value(
                self._movable_logic.readback_signal
            ):
                yield WatcherUpdate(
                    current=current_position,
                    initial=old_position,
                    target=new_position,
                    name=self.name,
                    unit=units,
                    precision=precision,
                )
        if not self._set_success:
            raise RuntimeError("Motor was stopped")

    async def stop(self, success=False):
        """Request to stop moving and return immediately."""
        self._set_success = success
        await self._movable_logic.stop()

    async def locate(self) -> Location[float]:
        """Return the current setpoint and readback of the motor."""
        setpoint, readback = await asyncio.gather(
            self._movable_logic.setpoint_signal.get_value(),
            self._movable_logic.readback_signal.get_value(),
        )
        return Location(setpoint=setpoint, readback=readback)

    def subscribe_reading(self, function: Callback[dict[str, Reading[float]]]) -> None:
        """Subscribe to reading."""
        self._movable_logic.readback_signal.subscribe_reading(function)

    subscribe = subscribe_reading

    def clear_sub(self, function: Callback[dict[str, Reading[float]]]) -> None:
        """Unsubscribe."""
        self._movable_logic.readback_signal.clear_sub(function)
