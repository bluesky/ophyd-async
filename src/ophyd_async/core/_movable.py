import asyncio
from abc import ABC, abstractmethod

from bluesky.protocols import Locatable, Location, Reading, Stoppable, Subscribable

from ._device import Device, DeviceMock, default_mock_class
from ._mock_signal_utils import callback_on_mock_put, set_mock_value
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
    """Movable logic for stopping and checking valid moves of a StandardMovable."""

    setpoint_signal: SignalRW[float]
    readback_signal: SignalR[float]

    @abstractmethod
    async def stop(self):
        """Stop the motion."""

    @abstractmethod
    async def check_move(self, old_position: float, new_position: float) -> None:
        """Check the move is valid."""

    @abstractmethod
    async def calculate_timeout(
        self, old_position: float, new_position: float
    ) -> float:
        """Calculate valid timeout for a move."""

    @abstractmethod
    async def get_units_precision(self) -> tuple[str | None, int | None]:
        """Return the units and precision."""


class InstanMovableMock(DeviceMock["StandardMovable"]):
    """Mock behaviour that instantly moves readback to setpoint."""

    async def connect(self, device: "StandardMovable") -> None:
        """Mock signals to do an instant move on setpoint write."""
        setpoint = device._movable_logic.setpoint_signal  # noqa: SLF001
        readback = device._movable_logic.readback_signal  # noqa: SLF001

        # When setpoint is written to, immediately update readback and done flag
        def _instant_move(value):
            set_mock_value(readback, value)  # Arrive instantly

        callback_on_mock_put(setpoint, _instant_move)


@default_mock_class(InstanMovableMock)
class StandardMovable(Device, Locatable[float], Stoppable, Subscribable):
    """Device that provides standard logic for moving.

    This class must be inherited and have ``add_movable_logic`` called.
    """

    # Whether set() should complete successfully or not
    _set_success = True
    __movable_logic: MovableLogic | None = None

    def add_movable_logic(self, logic: MovableLogic):
        if self.__movable_logic is not None:
            raise RuntimeError("Device already has movable logic.")
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
        """Move to the given value."""
        self._set_success = True
        old_position, (units, precision) = await asyncio.gather(
            self._movable_logic.setpoint_signal.get_value(),
            self._movable_logic.get_units_precision(),
        )
        await self._movable_logic.check_move(old_position, new_position)

        if timeout is CALCULATE_TIMEOUT:
            timeout = await self._movable_logic.calculate_timeout(
                old_position, new_position
            )
        async with self._movable_logic.setpoint_signal.set(
            new_position, timeout=timeout
        ):
            async for current_position in observe_value(
                self._movable_logic.readback_signal
            ):
                if not self._set_success:
                    raise RuntimeError(f"Motor {self.name} was stopped.")

                yield WatcherUpdate(
                    current=current_position,
                    initial=old_position,
                    target=new_position,
                    name=self.name,
                    unit=units,
                    precision=precision,
                )
        if not self._set_success:
            raise RuntimeError(f"Motor {self.name} was stopped.")

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
