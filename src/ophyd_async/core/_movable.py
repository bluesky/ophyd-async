import asyncio
import time
import warnings
from abc import abstractmethod
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field, replace
from typing import Generic

from bluesky.protocols import (
    Checkable,
    Locatable,
    Location,
    Reading,
    Stoppable,
    Subscribable,
)

from ._device import DeviceMock, default_mock_class
from ._mock_signal_utils import callback_on_mock_put, set_mock_value
from ._signal import SignalR, SignalRW, observe_value, set_and_wait_for_other_value
from ._signal_backend import SignalDatatypeT
from ._standard_base import Logic, StoppedError, _StandardBase
from ._status import AsyncStatus, WatchableAsyncStatus
from ._utils import (
    CALCULATE_TIMEOUT,
    CalculatableTimeout,
    Callback,
    WatcherUpdate,
    abstract_cached_property,
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
class MovableLogic(Logic, Generic[SignalDatatypeT]):
    """Minimum logic needed for controlling a `StandardMovable`.

    Inherit it to say how to stop the motion, and optionally to check a move is
    valid, calculate a timeout for a move, and add units and precision. Subclasses
    can also override `move` if more control is needed over the move itself.
    """

    setpoint: SignalRW[SignalDatatypeT]
    readback: SignalR[SignalDatatypeT]

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if "stop" in cls.__dict__:
            warnings.warn(
                f"{cls.__name__}.stop() is deprecated: rename it to "
                "ensure_stopped(), which must wait until the motion has stopped",
                DeprecationWarning,
                stacklevel=2,
            )
            if "ensure_stopped" not in cls.__dict__:
                cls.ensure_stopped = cls.__dict__["stop"]

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


async def watch_readback(
    logic: MovableLogic[SignalDatatypeT],
    status: AsyncStatus,
    target: SignalDatatypeT,
    initial: SignalDatatypeT | None = None,
) -> AsyncGenerator[WatcherUpdate[SignalDatatypeT], None]:
    """Report the progress of a move by watching the readback of a logic.

    Yields a `WatcherUpdate` for each readback value until the status is done,
    then re-raises any error the status raised. Use it from a `FlyableLogic`
    hook that moves the logic's device, returning it from the hook as its
    progress.

    :param logic: the logic whose readback is watched, and which supplies the
        units and precision.
    :param status: the status of the move, which is left running.
    :param target: the value the move is going to.
    :param initial: where the move started from. Defaults to the readback now.
    """
    if initial is None:
        initial = await logic.readback.get_value()
    units, precision = await logic.get_units_precision()
    async for current in observe_value(logic.readback, done_status=status):
        yield WatcherUpdate(
            current=current,
            initial=initial,
            target=target,
            name=logic.readback.name,
            unit=units,
            precision=precision,
        )


class InstantMovableMock(DeviceMock["StandardMovable"]):
    """Mock behaviour that instantly moves readback to setpoint."""

    async def connect(self, device: "StandardMovable") -> None:
        """Mock signals to do an instant move on setpoint write."""

        def _instant_move(value):
            set_mock_value(device.logic.readback, value)  # Arrive instantly

        callback_on_mock_put(device.logic.setpoint, _instant_move)


@default_mock_class(InstantMovableMock)
class StandardMovable(
    _StandardBase,
    Locatable[SignalDatatypeT],
    Checkable[SignalDatatypeT],
    Stoppable,
    Subscribable[SignalDatatypeT],
    Generic[SignalDatatypeT],
):
    """Device that provides standard logic for moving.

    Provide `logic` as a `@cached_property`.

    `set()` moves to a value. Only one runs at a time: a new `set()` ends the
    one in progress, which raises `StoppedError`.

    `stop()` ends the `set()` in progress, which raises `StoppedError`, or
    finishes normally if called with `success=True`. It then calls
    `logic.ensure_stopped()` to halt the hardware, without waiting for the
    `set()` to finish.

    A `StandardMovable` does nothing on `stage()` or `unstage()` by itself.
    Combined with `StandardFlyable`, those run the logic's
    `ensure_ready` and `ensure_stopped`, which also halt a `set()` in progress.
    `stop()` does not end a `prepare()` or fly, only `unstage()` does, but it
    still halts the hardware, so a `stop()` during the run-up can leave
    `prepare()` finishing short of the start.
    """

    # Ends the latest set(): resolved by stop(), or by the next set(), with the
    # error to raise as a value, so a future nobody awaits raises nothing
    _set_stop: asyncio.Future[Exception | None] | None = None

    @abstract_cached_property
    @abstractmethod
    def logic(self) -> MovableLogic[SignalDatatypeT]:
        """The logic object that describes how this device moves.

        Subclasses must implement this as a `@cached_property` returning a
        `MovableLogic`.

        A Device that is movable *and* flyable (e.g. `Motor`) implements this
        once with a logic object that inherits both `MovableLogic` and
        `FlyableLogic`.
        """
        raise NotImplementedError

    async def check_value(self, value: SignalDatatypeT) -> None:
        """Check the move is valid before doing it."""
        await self.logic.check_move(value)

    def set(
        self,
        new_position: SignalDatatypeT,
        timeout: CalculatableTimeout = CALCULATE_TIMEOUT,
    ) -> WatchableAsyncStatus[SignalDatatypeT]:
        """Move to the given value, ending any `set()` in progress."""
        self._end_set(StoppedError(f"Device {self.name}: superseded by a new set()"))
        self._set_stop = asyncio.get_running_loop().create_future()
        return WatchableAsyncStatus(
            self._set(new_position, timeout),
            name=self.name,
            stop=self._set_stop,
        )

    async def _set(
        self, new_position: SignalDatatypeT, timeout: CalculatableTimeout
    ) -> AsyncGenerator[WatcherUpdate[SignalDatatypeT], None]:
        old_position = await self.logic.readback.get_value()
        await self.logic.check_move(new_position)
        if timeout == CALCULATE_TIMEOUT:
            move_timeout = await self.logic.calculate_timeout(
                old_position, new_position
            )
        else:
            move_timeout = timeout
        move = self.logic.move(
            new_position=new_position, timeout=MoveTimeout(move_timeout)
        )
        async with AsyncStatus(move) as move_status:
            async for update in watch_readback(
                self.logic, move_status, target=new_position, initial=old_position
            ):
                yield replace(update, name=self.name)

    async def stop(self, *, success: bool = False) -> None:
        """End any `set()` in progress, then run `ensure_stopped`.

        The `set()` raises `StoppedError`, or finishes if `success`, whether or not
        `move()` returned early. A `set()` stopped before its move started leaves the
        hardware alone, and a second `stop()` only runs `ensure_stopped` again. A
        `prepare()` or fly of a `StandardFlyable` is not ended, only halted.
        """
        self._end_set(
            None if success else StoppedError(f"Device {self.name} was stopped.")
        )
        await self.logic.ensure_stopped()

    def _end_set(self, error: StoppedError | None) -> None:
        if self._set_stop is not None and not self._set_stop.done():
            self._set_stop.set_result(error)

    def set_name(self, name: str, *, child_name_separator: str | None = None) -> None:
        super().set_name(name, child_name_separator=child_name_separator)
        # Readback should be named the same as its parent in read()
        self.logic.readback.set_name(name)

    async def locate(self) -> Location[SignalDatatypeT]:
        """Return the current setpoint and readback of the device."""
        setpoint, readback = await asyncio.gather(
            self.logic.setpoint.get_value(),
            self.logic.readback.get_value(),
        )
        return Location(setpoint=setpoint, readback=readback)

    def subscribe_reading(
        self, function: Callback[dict[str, Reading[SignalDatatypeT]]]
    ) -> None:
        """Subscribe to reading."""
        self.logic.readback.subscribe_reading(function)

    subscribe = subscribe_reading

    def clear_sub(
        self, function: Callback[dict[str, Reading[SignalDatatypeT]]]
    ) -> None:
        """Unsubscribe."""
        self.logic.readback.clear_sub(function)
