import asyncio
import contextlib
from abc import abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import replace
from functools import cached_property
from typing import Any, Generic, TypeVar, cast

from bluesky.protocols import Flyable, Preparable
from pydantic import Field
from typing_extensions import Sentinel
from typing_extensions import TypeVar as TypeVarWithDefault

from ._movable import MovableLogic
from ._standard_base import (
    Logic,
    TransitionError,
    _StandardBase,
    _State,
    _StateMachine,
)
from ._status import AsyncStatus, WatchableAsyncStatus
from ._utils import (
    CALCULATE_TIMEOUT,
    CalculatableTimeout,
    ConfinedModel,
    WatcherUpdate,
    abstract_cached_property,
    cancel_and_wait,
)

#: The per-scan info passed to `FlyableLogic.prepare_to_fly` (often a
#: [`scanspec.core.Path`](inv:scanspec#scanspec.core.Path), but any type).
PrepareT = TypeVar("PrepareT")
#: The context yielded by `FlyableLogic.prepare_to_fly` and passed on to `fly`.
#: Defaults to `None`, for flyers that carry no state from prepare to fly.
CtxT = TypeVarWithDefault("CtxT", default=None)


#: Yielded by `FlyableLogic.fly` to mark the flyer as flying.
KICKED_OFF = Sentinel("KICKED_OFF")


class FlyableLogic(Logic, Generic[PrepareT, CtxT]):
    """Minimum logic needed for controlling a `StandardFlyable`.

    Inherit and fill in the hooks for a particular flyable (e.g. a motion or
    trigger system). This base holds no state; concrete subclasses are typically
    `@dataclass`es that hold whatever signals or sub-devices they need as fields.

    What a scan needs is carried by a context object: `prepare_to_fly` yields it,
    and it is passed to `fly` and to the next `prepare_to_fly`. `StandardFlyable`
    holds it from a finished `prepare()` until the next `stage()` and enforces the
    call ordering, so subclasses do not need to guard against being called out of
    order.

    The type parameters are the per-scan info `PrepareT` and the context `CtxT`,
    which defaults to `None`, so `FlyableLogic[PrepareT]` is a logic without one.
    The hooks are not named after bluesky verbs, so a logic passed to a plan is not
    mistaken for a device.
    """

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        renamed = {
            "on_prepare": "prepare_to_fly",
            "on_kickoff": "fly",
            "on_complete": "fly",
            "on_stage": "ensure_ready",
            "on_unstage": "ensure_stopped",
            # A logic that is also a MovableLogic gets its deprecation alias
            **({} if issubclass(cls, MovableLogic) else {"stop": "ensure_stopped"}),
        }
        if stale := [name for name in renamed if name in cls.__dict__]:
            raise TypeError(
                f"{cls.__name__} defines {', '.join(stale)}, which FlyableLogic no "
                "longer calls: "
                + ", ".join(f"{name} -> {renamed[name]}" for name in stale)
            )

    async def ensure_ready(self) -> None:
        """Get the device ready on `stage()`. Defaults to `ensure_stopped`."""
        await self.ensure_stopped()

    @abstractmethod
    def prepare_to_fly(
        self, name: str, value: PrepareT, previous_ctx: CtxT | None
    ) -> AsyncGenerator[CtxT | WatcherUpdate, None]:
        """Work out the scan, set up the hardware, and yield the scan's context.

        Write it as an async generator whose first yield is the context; any
        later yields are `WatcherUpdate`s reporting the progress of the slow part,
        e.g. moving to the start of the scan. `prepare()` raises `TypeError` if the
        first yield is not the context. It finishes when the generator does, and
        only then is the context kept. Own anything it starts with `async with`, so
        it is stopped if `prepare()` fails or is cancelled:

        ```python
        async def prepare_to_fly(self, name, value, previous_ctx):
            ctx = MyCtx(start=value.start)
            yield ctx
            async with AsyncStatus(self.move(ctx.start, timeout)) as status:
                async for update in watch_readback(self, status, target=ctx.start):
                    yield update
        ```

        :param name: the name of the device.
        :param value: the per-scan info for this fly scan.
        :param previous_ctx: the context of the last finished `prepare()` since
            `stage()`, or `None` if there was none.
        """

    @abstractmethod
    def fly(self, ctx: CtxT) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        """Run the fly scan: yield `KICKED_OFF` once flying, then its progress.

        Write it as an async generator. `kickoff()` finishes at the first yield,
        which must be `KICKED_OFF`; later yields go to the watchers of
        `complete()`, which finishes when the generator does.

        `StandardFlyable` runs it in the task of the status `complete()` returns,
        and cancels that task on `unstage()`. Do not leave anything
        running that this generator does not wait for: own a status with
        `async with`, and run concurrent work through `watch_readback` or an
        `asyncio.TaskGroup`. For example:

        ```python
        async def fly(self, ctx):
            async with AsyncStatus(self.move(ctx.end, timeout)) as status:
                await asyncio.sleep(ctx.acceleration_time)
                yield KICKED_OFF
                async for update in watch_readback(self, status, target=ctx.end):
                    yield update
        ```

        :param ctx: the context yielded by `prepare_to_fly`.
        """

    def with_device(self, name: str = "") -> "StandardFlyable[Any, Any]":
        """Wrap this logic in an ephemeral `StandardFlyable` for use in a plan."""
        return _EphemeralFlyable(self, name=name)


class FlyMotorInfo(ConfinedModel):
    """Minimal set of information required to fly a motor."""

    start_position: float = Field(frozen=True)
    """Absolute position of the motor once it finishes accelerating to desired
    velocity, in motor EGUs"""

    end_position: float = Field(frozen=True)
    """Absolute position of the motor once it begins decelerating from desired
    velocity, in EGUs"""

    time_for_move: float = Field(frozen=True, gt=0)
    """Time taken for the motor to get from start_position to end_position, excluding
    run-up and run-down, in seconds."""

    timeout: CalculatableTimeout = Field(frozen=True, default=CALCULATE_TIMEOUT)
    """Maximum time for the complete motor move, including run up and run down.
    Defaults to `time_for_move` + run up and run down times + 10s."""

    @property
    def speed(self) -> float:
        """Calculate the speed of the constant velocity phase, always positive."""
        return abs(self.end_position - self.start_position) / self.time_for_move

    def ramp_up_start_pos(self, acceleration_time: float) -> float:
        """Calculate the start position with run-up distance added on."""
        return self.start_position - self._ramp_distance(acceleration_time)

    def ramp_down_end_pos(self, acceleration_time: float) -> float:
        """Calculate the end position with run-down distance added on."""
        return self.end_position + self._ramp_distance(acceleration_time)

    def _ramp_distance(self, acceleration_time: float) -> float:
        # Signed so run-up/run-down land on the correct side for either direction.
        return (
            acceleration_time
            * (self.end_position - self.start_position)
            / (2 * self.time_for_move)
        )


class StandardFlyable(
    _StandardBase,
    Preparable,
    Flyable,
    Generic[PrepareT, CtxT],
):
    """Device that flies with a `FlyableLogic`.

    Provide `logic` as a `@cached_property`, or call `FlyableLogic.with_device` for an
    ephemeral flyer. Call `stage()`, `prepare()`, `kickoff()` and `complete()` in that
    order, otherwise they raise `TransitionError`; prepare again once complete.

    `stage()` runs `logic.ensure_ready`, `prepare()` runs `logic.prepare_to_fly`,
    `kickoff()` starts `logic.fly` and returns at `KICKED_OFF`, and `complete()`
    returns the status of that fly. If any of them fails, every verb but `unstage()`
    raises until it is called. `unstage()` cancels a running `prepare()` or fly, then
    runs `logic.ensure_stopped`.
    """

    # The context of the last finished prepare(), until the next stage()
    _ctx: CtxT | None = None
    # The fly started by kickoff(), returned by complete() until the next prepare()
    # or stage()
    _fly_status: WatchableAsyncStatus | None = None

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Composes with any other _StandardBase mix-in, e.g. StandardReadable
        self._stage_funcs += (self.__on_stage,)
        self._unstage_funcs += (self.__on_unstage,)

    @cached_property
    def _state(self) -> _StateMachine:
        # super()._state caches the base machine in the instance first, then this
        # property overwrites it with the combined one
        return super()._state | {
            _State.PREPARING: {_State.STAGED, _State.FLOWN},
            _State.FLYING: {_State.PREPARED},
        }

    @abstract_cached_property
    @abstractmethod
    def logic(self) -> FlyableLogic[PrepareT, CtxT]:
        """The logic object that describes how this device flies.

        A static flyer (e.g. `Motor`) provides this as a `@cached_property` that
        builds a `FlyableLogic` from its signals. An ephemeral flyer created by
        `FlyableLogic.with_device` returns the logic it was created with.

        A Device that is flyable *and* movable implements this once with a logic
        object inheriting both `FlyableLogic` and `MovableLogic`.
        """
        raise NotImplementedError

    async def __on_stage(self) -> None:
        # Forget the last run
        self._ctx = None
        self._fly_status = None
        await self.logic.ensure_ready()

    async def __on_unstage(self) -> None:
        # Always stop, a set() in progress included
        await self.logic.ensure_stopped()

    @WatchableAsyncStatus.wrap
    async def prepare(self, value: PrepareT) -> AsyncGenerator[WatcherUpdate, None]:
        """Set up the fly scan and move to its start.

        Reports the progress the logic's `prepare_to_fly` yields after the
        context.
        """
        # A failed prepare must leave nothing to kick off
        async with self._state.transition(_State.PREPARING, end=_State.PREPARED):
            self._fly_status = None
            previous_ctx, self._ctx = self._ctx, None
            hook = f"{type(self.logic).__name__}.prepare_to_fly()"
            steps = self.logic.prepare_to_fly(self.name, value, previous_ctx)
            async with contextlib.aclosing(steps):
                try:
                    ctx = await anext(steps)
                except StopAsyncIteration:
                    raise RuntimeError(
                        f"{hook} finished without yielding its context"
                    ) from None
                if isinstance(ctx, WatcherUpdate):
                    raise TypeError(f"{hook} must yield its context first, not {ctx!r}")
                async for update in steps:
                    if not isinstance(update, WatcherUpdate):
                        raise TypeError(
                            f"{hook} must yield only WatcherUpdates after its "
                            f"context, not {update!r}"
                        )
                    yield replace(update, name=self.name)
                self._ctx = ctx

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        """Start the logic's `fly`, returning once it has yielded `KICKED_OFF`."""
        kicked_off: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        status = WatchableAsyncStatus(self._fly(kicked_off), name=self.name)
        try:
            await asyncio.wait(
                [kicked_off, status.task], return_when=asyncio.FIRST_COMPLETED
            )
        except BaseException:
            # Cancelled, even just after KICKED_OFF: end the fly, report our cancel
            with contextlib.suppress(Exception):
                await cancel_and_wait(status.task)
            raise
        if not kicked_off.done():
            # The fly ended before KICKED_OFF, raise why
            await status
        self._fly_status = status

    async def _fly(
        self, kicked_off: asyncio.Future[None]
    ) -> AsyncGenerator[WatcherUpdate, None]:
        async with self._state.transition(_State.FLYING, end=_State.FLOWN):
            hook = f"{type(self.logic).__name__}.fly()"
            # FLYING is only entered from PREPARED, so the context is set
            fly = self.logic.fly(cast(CtxT, self._ctx))
            async with contextlib.aclosing(fly):
                try:
                    first = await anext(fly)
                except StopAsyncIteration:
                    raise RuntimeError(
                        f"{hook} finished without yielding KICKED_OFF"
                    ) from None
                if first is not KICKED_OFF:
                    raise TypeError(
                        f"{hook} must yield KICKED_OFF first, not {first!r}"
                    )
                kicked_off.set_result(None)
                async for update in fly:
                    if not isinstance(update, WatcherUpdate):
                        raise TypeError(
                            f"{hook} must yield only WatcherUpdates after "
                            f"KICKED_OFF, not {update!r}"
                        )
                    yield replace(update, name=self.name)

    def complete(self) -> WatchableAsyncStatus[Any]:
        """Return the status of the fly the last `kickoff()` started.

        It reports the progress `fly` yields after `KICKED_OFF`, starting with the
        latest, and finishes when `fly` does. Cancelling it cancels the fly. A failed
        fly's status is returned until the next `prepare()` or `stage()`.
        """
        if self._fly_status is None:
            raise TransitionError(
                f"{self.name}: cannot complete from {self._state.state.name}, "
                "allowed only after kickoff()"
            )
        return self._fly_status


class _EphemeralFlyable(StandardFlyable[PrepareT, CtxT]):
    """A `StandardFlyable` with the logic it was created with."""

    def __init__(self, logic: FlyableLogic[PrepareT, CtxT], name: str = "") -> None:
        self._logic = logic
        super().__init__(name=name)

    @cached_property
    def logic(self) -> FlyableLogic[PrepareT, CtxT]:
        return self._logic
