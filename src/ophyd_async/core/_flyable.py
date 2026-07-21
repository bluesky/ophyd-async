import asyncio
from abc import abstractmethod
from collections.abc import AsyncIterator
from enum import Enum
from functools import cached_property
from typing import Generic, TypeVar, cast

from bluesky.protocols import Flyable, Preparable
from pydantic import Field

from ._movable import MovableLogic
from ._signal import observe_value
from ._standard_base import _StandardBase
from ._status import AsyncStatus, WatchableAsyncStatus
from ._utils import (
    CALCULATE_TIMEOUT,
    CalculatableTimeout,
    ConfinedModel,
    WatcherUpdate,
)

#: The per-scan info passed to `FlyableLogic.on_prepare` (often a
#: [`scanspec.core.Path`](inv:scanspec#scanspec.core.Path), but any type).
PrepareT = TypeVar("PrepareT")
#: The context object threaded from `on_prepare` through `on_kickoff` to
#: `on_complete`. Use `None` for flyers that carry no state between stages.
CtxT = TypeVar("CtxT")


class FlyableLogic(Generic[PrepareT, CtxT]):
    """Minimum logic needed for controlling a `StandardFlyable`.

    Inherit and fill in the hooks for a particular flyable (e.g. a motion or
    trigger system). This base holds no state; concrete subclasses are typically
    `@dataclass`es that hold whatever signals or sub-devices they need as fields.

    State that must be carried between stages is threaded through an explicit
    context object rather than stored on the logic: `on_prepare` returns it,
    `on_kickoff` receives and returns it, and `on_complete` receives it.
    `StandardFlyable` owns that context and enforces the call ordering, so
    subclasses do not need to guard against being called out of order. A flyer
    with no cross-stage state uses `None` for the context (see the PandA trigger
    logics).
    """

    @abstractmethod
    async def on_prepare(self, value: PrepareT) -> CtxT:
        """Move to the start of the fly scan, set it up, and return its context.

        :param value: the per-scan info for this fly scan.
        """

    @abstractmethod
    async def on_kickoff(self, ctx: CtxT) -> CtxT:
        """Start the fly scan.

        :param ctx: the context returned by `on_prepare`.

        Return the (possibly updated) context to be passed to `on_complete`.
        """

    @abstractmethod
    async def on_complete(self, ctx: CtxT) -> None:
        """Block until the fly scan is done.

        :param ctx: the context returned by `on_kickoff`.
        """

    async def stop(self) -> None:
        """Stop/disarm the flyer and wait for everything to be stopped.

        Called by `on_stage` and `on_unstage` by default; override those instead
        if stage and unstage need to differ.
        """
        pass

    async def on_stage(self) -> None:
        """Set the flyer up on `stage()`. Defaults to `stop`."""
        await self.stop()

    async def on_unstage(self) -> None:
        """Clean the flyer up on `unstage()`. Defaults to `stop`."""
        await self.stop()

    def with_device(self, name: str = "") -> "StandardFlyable":
        """Wrap this logic in an ephemeral `StandardFlyable` for use in a plan."""
        flyer = StandardFlyable(name=name)
        flyer.flyable_logic = self
        return flyer


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


class _FlyStage(Enum):
    """Lifecycle stage of a `StandardFlyable`, used to enforce call ordering."""

    IDLE = "IDLE"
    PREPARED = "PREPARED"
    KICKED_OFF = "KICKED_OFF"


class StandardFlyable(
    _StandardBase,
    Preparable,
    Flyable,
    Generic[PrepareT, CtxT],
):
    """Device that provides standard logic for flying.

    This class must be inherited and have a `flyable_logic` @cached_property.
    For an ephemeral flyer in a plan, call `FlyableLogic.with_device` instead of
    inheriting. It owns the context threaded between the logic's stages and
    enforces prepare -> kickoff -> complete ordering. `stage()`/`unstage()` run
    the logic's `on_stage`/`on_unstage` (which default to `stop`) and reset the
    context.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Contribute the flyer's stage/unstage hooks (composes with any other
        # _StandardBase mix-in, e.g. StandardReadable on a Motor).
        self._stage_funcs += (self._on_stage,)
        self._unstage_funcs += (self._on_unstage,)
        # Context threaded prepare -> kickoff -> complete. Only meaningful once
        # prepared; access is guarded by _fly_stage.
        self._fly_ctx: CtxT = cast(CtxT, None)
        self._fly_stage = _FlyStage.IDLE

    @cached_property
    def flyable_logic(self) -> FlyableLogic[PrepareT, CtxT]:
        """The logic object that describes how this device flies.

        A static flyer (e.g. `Motor`) provides this as a `@cached_property` that
        builds a `FlyableLogic` from its signals. An ephemeral flyer created by
        `FlyableLogic.with_device` has it set directly on the instance.
        """
        raise NotImplementedError(
            f"{type(self).__name__} has no flyable_logic; override it as a "
            "@cached_property or create the flyer via FlyableLogic.with_device()"
        )

    def _reset_fly_state(self) -> None:
        self._fly_ctx = cast(CtxT, None)
        self._fly_stage = _FlyStage.IDLE

    @AsyncStatus.wrap
    async def _on_stage(self) -> None:
        await self.flyable_logic.on_stage()
        self._reset_fly_state()

    @AsyncStatus.wrap
    async def _on_unstage(self) -> None:
        await self.flyable_logic.on_unstage()
        self._reset_fly_state()

    @AsyncStatus.wrap
    async def prepare(self, value: PrepareT) -> None:
        """Move to the start and set up the fly scan."""
        self._fly_ctx = await self.flyable_logic.on_prepare(value)
        self._fly_stage = _FlyStage.PREPARED

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        """Start the fly scan."""
        if self._fly_stage is not _FlyStage.PREPARED:
            raise RuntimeError(
                f"{self.name}: prepare() must be called before kickoff()"
            )
        self._fly_ctx = await self.flyable_logic.on_kickoff(self._fly_ctx)
        self._fly_stage = _FlyStage.KICKED_OFF

    @WatchableAsyncStatus.wrap
    async def complete(self) -> AsyncIterator[WatcherUpdate]:
        """Block until the fly scan is done.

        If the logic is also a `MovableLogic` (e.g. a flying `Motor`), report
        progress to watchers by observing its readback while the fly scan runs,
        reusing the same watcher-update stream as `StandardMovable.set`. Flyers
        whose logic is not movable simply block with no progress updates.
        """
        if self._fly_stage is not _FlyStage.KICKED_OFF:
            raise RuntimeError(
                f"{self.name}: kickoff() must be called before complete()"
            )
        logic = self.flyable_logic
        if isinstance(logic, MovableLogic):
            initial, target, (units, precision) = await asyncio.gather(
                logic.readback.get_value(),
                logic.setpoint.get_value(),
                logic.get_units_precision(),
            )
            async with AsyncStatus(logic.on_complete(self._fly_ctx)) as completing:
                async for current_position in observe_value(
                    logic.readback, done_status=completing
                ):
                    yield WatcherUpdate(
                        current=current_position,
                        initial=initial,
                        target=target,
                        name=self.name,
                        unit=units,
                        precision=precision,
                    )
        else:
            await self.flyable_logic.on_complete(self._fly_ctx)
        self._fly_stage = _FlyStage.IDLE
