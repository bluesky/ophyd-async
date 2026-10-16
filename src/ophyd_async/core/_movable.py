import asyncio
import time
from abc import abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from functools import cached_property
from typing import Generic

from bluesky.protocols import (
    Checkable,
    Locatable,
    Location,
    Reading,
    Stoppable,
    Subscribable,
)

from ._device import Device, DeviceMock, default_mock_class
from ._mock_signal_utils import callback_on_mock_put, set_mock_value
from ._signal import SignalR, SignalRW, observe_value, set_and_wait_for_other_value
from ._signal_backend import SignalDatatypeT
from ._status import AsyncStatus, WatchableAsyncStatus
from ._utils import (
    CALCULATE_TIMEOUT,
    CalculatableTimeout,
    Callback,
    WatcherUpdate,
)


@dataclass
class MoveTimeout:
    """The time left for a move to complete before it times out."""

    timeout: float | None
    start_time: float = field(default_factory=time.monotonic)

    def __call__(self) -> float | None:
        """Remaining time for a calculated timeout left for the move to use."""
        if self.timeout is None:
            return None
        elapsed = time.monotonic() - self.start_time
        return max(0.0, self.timeout - elapsed)


TimeoutCalculator = Callable[[], float | None]


@dataclass
class MovableLogic(Generic[SignalDatatypeT]):
    """Minimum logic needed for controlling a `StandardMovable`.

    Can be inherited to add specialised logic for stop, checking if a move is valid,
    calculate a valid timeout for a move, and add units and precision. Sub classes can
    also override the `get_move_status` and `move` methods if more control is needed
    to provide a custom AsyncStatus and to handle the move logic.
    """

    setpoint: SignalRW[SignalDatatypeT]
    readback: SignalR[SignalDatatypeT]

    async def stop(self) -> None:
        """Optional hook to add logic on how to stop the motion."""
        pass

    async def check_move(self, new_position: SignalDatatypeT) -> None:
        """Optional hook to validate the move.

        Should raise an exception if the move is not valid, e.g. if the new
        position is outside soft limits.
        """
        pass

    async def calculate_timeout(
        self, old_position: SignalDatatypeT, new_position: SignalDatatypeT
    ) -> float | None:
        """Optional hook to calculate valid timeout for a move."""
        return None

    async def get_units_precision(self) -> tuple[str | None, int | None]:
        """Optional hook to return the units and precision."""
        datakey = (await self.readback.describe())[self.readback.name]
        return datakey.get("units"), datakey.get("precision")

    async def move(
        self, new_position: SignalDatatypeT, timeout: TimeoutCalculator
    ) -> None:
        """Move the device, waiting for the readback to reach the correct position.

        ```{note}
        The default implementation waits for the readback to be **exactly**
        equal to `new_position`. For floating-point positions this may never
        be satisfied; override this method to use an appropriate tolerance
        check (e.g. `np.isclose`).
        ```
        """
        await set_and_wait_for_other_value(
            self.setpoint,
            new_position,
            self.readback,
            new_position,
            timeout=timeout(),
        )


class InstantMovableMock(DeviceMock["StandardMovable"]):
    """Mock behaviour that instantly moves readback to setpoint."""

    async def connect(self, device: "StandardMovable") -> None:
        """Mock signals to do an instant move on setpoint write."""

        def _instant_move(value):
            set_mock_value(device.movable_logic.readback, value)  # Arrive instantly

        callback_on_mock_put(device.movable_logic.setpoint, _instant_move)


class StopState(Enum):
    NONE = "NONE"
    USER_SUCCESS = "USER_SUCCESS"
    USER_FAILURE = "USER_FAILURE"


@default_mock_class(InstantMovableMock)
class StandardMovable(
    Device,
    Locatable[SignalDatatypeT],
    Checkable[SignalDatatypeT],
    Stoppable,
    Subscribable[SignalDatatypeT],
    Generic[SignalDatatypeT],
):
    """Device that provides standard logic for moving.

    This class must be inherited and have a `movable_logic` @cached_property.
    If stop is called while moving, it will raise a RuntimeError.
    """

    # Whether set() should complete successfully or raise an error due to stop called or
    # due to timeout.
    _stop_state: Enum = StopState.NONE
    _move_status: AsyncStatus | None = None

    @cached_property
    @abstractmethod
    def movable_logic(self) -> MovableLogic:
        """The logic object that describes how this device moves.

        This is intentionally public so that mock helpers (e.g.
        `InstantMovableMock`) and subclasses can access the `setpoint` and
        `readback` signals directly. Subclasses must implement this as a
        `@cached_property` that returns a `MovableLogic` instance.
        """

    async def check_value(self, value: SignalDatatypeT) -> None:
        """Check the move is valid before doing it."""
        await self.movable_logic.check_move(value)

    @WatchableAsyncStatus.wrap
    async def set(
        self,
        new_position: SignalDatatypeT,
        timeout: CalculatableTimeout = CALCULATE_TIMEOUT,
    ):
        """Move to the given value."""
        self._stop_state = StopState.NONE
        old_position, (units, precision) = await asyncio.gather(
            self.movable_logic.readback.get_value(),
            self.movable_logic.get_units_precision(),
        )
        await self.movable_logic.check_move(new_position)

        if timeout == CALCULATE_TIMEOUT:
            move_timeout = await self.movable_logic.calculate_timeout(
                old_position, new_position
            )
        else:
            move_timeout = timeout

        try:
            async with AsyncStatus(
                self.movable_logic.move(
                    new_position=new_position, timeout=MoveTimeout(move_timeout)
                )
            ) as self._move_status:
                async for current_position in observe_value(
                    self.movable_logic.readback,
                    done_status=self._move_status,
                ):
                    yield WatcherUpdate(
                        current=current_position,
                        initial=old_position,
                        target=new_position,
                        name=self.name,
                        unit=units,
                        precision=precision,
                    )
        # Convert cancellation into the appropriate stop result.
        # If stop(success=True) was called, complete without raising.
        # If stop(success=False) was called, raise a RuntimeError below.
        # If not stopped but times out, show the CancelledError from the timeout.
        except asyncio.CancelledError:
            if self._stop_state == StopState.NONE:
                raise
        finally:
            self._move_status = None

        # Raise error if needed, reset stop state.
        stop_state = self._stop_state
        self._stop_state = StopState.NONE
        if stop_state == StopState.USER_FAILURE:
            raise RuntimeError(f"Device {self.name} was stopped.")

    async def stop(self, success=False):
        """Request to stop moving and return immediately."""
        self._stop_state = StopState.USER_SUCCESS if success else StopState.USER_FAILURE
        await self.movable_logic.stop()
        if self._move_status:
            self._move_status.task.cancel()

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
