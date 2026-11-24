import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from enum import Enum
from functools import cached_property
from typing import final

from ._device import Device
from ._protocol import AsyncStageable
from ._status import AsyncStatus
from ._utils import _gather_or_cancel_all, cancel_and_wait


class _State(Enum):
    """Every state of `_StandardBase`, `StandardFlyable` and `StandardDetector`.

    A verb runs in an -ING state, holding its task so `unstage()` can cancel it,
    then goes to its done state, or to ERROR if it fails. Each class in the stack
    adds the -ING states it needs and the done states each may start from.
    """

    # _StandardBase
    UNSTAGED = "UNSTAGED"
    STAGING = "STAGING"
    STAGED = "STAGED"
    # StandardFlyable
    PREPARING = "PREPARING"
    PREPARED = "PREPARED"
    FLYING = "FLYING"
    FLOWN = "FLOWN"
    # A verb failed: only unstage() leaves it
    ERROR = "ERROR"
    # StandardDetector
    TRIGGERING = "TRIGGERING"
    TRIGGERED = "TRIGGERED"


class TransitionError(RuntimeError):
    """A verb was called in a state that does not allow it."""


class _StateMachine:
    """Current state of a device, the verbs it may start and the running verb.

    :param device: the device, for error messages
    :param starts: each -ING state mapped to the done states it may start from
    """

    def __init__(self, device: Device, starts: Mapping[_State, set[_State]]) -> None:
        self._device = device
        self._starts = starts
        self.state = _State.UNSTAGED
        self._task: asyncio.Task | None = None

    @asynccontextmanager
    async def transition(
        self, during: _State, *, end: _State
    ) -> AsyncGenerator[None, None]:
        """Run a verb in the -ING state `during`, then go to `end`, or ERROR on failure.

        Safe to wrap `yield`s of an async generator. If `unstage()` has moved the
        machine on in the meantime, even into a new run of the same verb, this
        verb no longer owns the state and is left alone to finish cancelling.
        """
        allowed = self._starts.get(during, set())
        if self.state not in allowed:
            raise TransitionError(
                f"{self._device.name}: cannot go to {during.name} from "
                f"{self.state.name}, allowed from: "
                f"{', '.join(sorted(s.name for s in allowed))}"
            )
        self.state, self._task = during, asyncio.current_task()
        try:
            yield
        except BaseException:
            # Can be false: unstage cancelled this verb and moved the state on,
            # or an abandoned async generator was closed later from another task
            if self._task is asyncio.current_task():
                self.state, self._task = _State.ERROR, None
            raise
        else:
            if self._task is asyncio.current_task():
                self.state, self._task = end, None

    async def unstage(self) -> None:
        """Go to UNSTAGED from any state, cancelling the running verb."""
        verb, self._task = self._task, None
        self.state = _State.UNSTAGED
        if verb not in (None, asyncio.current_task()):
            await cancel_and_wait(verb)


class StoppedError(RuntimeError):
    """A set, prepare or fly was ended early by `stop()` or a new `set()`."""


class Logic(ABC):
    """Base of `MovableLogic` and `FlyableLogic`: stopping."""

    @abstractmethod
    async def ensure_stopped(self) -> None:
        """Stop the hardware and wait until it has stopped.

        Called by `StandardMovable.stop()`, which bluesky calls on pause and at
        the end of a run, and by `StandardFlyable` on `unstage()`.
        """


class _StandardBase(Device, AsyncStageable):
    """Base for `Device` mix-ins that contribute to `stage()`/`unstage()`.

    `StandardReadable`, `StandardFlyable` and similar mix-ins each need to run
    something on `stage()`/`unstage()`. They register callables into
    `_stage_funcs`/`_unstage_funcs`, which this base gathers. Each mix-in names
    its hooks `__on_stage`/`__on_unstage`, name-mangled so they never collide.
    """

    # Immutable defaults to avoid accidental sharing between instances
    _stage_funcs: tuple[Callable[[], Awaitable[None]], ...] = ()
    _unstage_funcs: tuple[Callable[[], Awaitable[None]], ...] = ()

    @final
    @cached_property
    def _state(self) -> _StateMachine:
        # cached_property as Device registration runs before super().__init__
        return _StateMachine(self, self._state_starts())

    def _state_starts(self) -> Mapping[_State, set[_State]]:
        """Each -ING state mapped to the done states it may start from.

        Subclasses add their own on top of `super()._state_starts()`.
        """
        return {_State.STAGING: {_State.UNSTAGED}}

    @AsyncStatus.wrap
    async def stage(self) -> None:
        async with self._state.transition(_State.STAGING, end=_State.STAGED):
            await _gather_or_cancel_all([func() for func in self._stage_funcs])

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        try:
            await self._state.unstage()
        finally:
            # The cancelled verb may raise its failure, the hardware stops anyway
            await _gather_or_cancel_all([func() for func in self._unstage_funcs])
