from abc import abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from functools import cached_property
from typing import Generic

from bluesky.protocols import Flyable, Preparable, Stageable
from pydantic import Field

from ._device import Device
from ._status import AsyncStatus, WatchableAsyncStatus
from ._utils import (
    CALCULATE_TIMEOUT,
    CalculatableTimeout,
    ConfinedModel,
    T,
    WatcherUpdate,
)


@dataclass
class FlyableLogic(Generic[T]):
    """Minimum logic needed for controlling a `StandardFlyable`.

    Inherit and fill in the hooks for a particular flyable (e.g. a motion or
    trigger system). Subclasses hold whatever signals or sub-devices they need
    as dataclass fields. `on_prepare` receives the per-scan info (often a
    [`scanspec.core.Path`](inv:scanspec#scanspec.core.Path), but any type `T`).
    """

    @abstractmethod
    async def on_prepare(self, value: T) -> None:
        """Move to the start of the fly scan and set it up."""

    @abstractmethod
    async def on_kickoff(self) -> None:
        """Start the fly scan."""

    @abstractmethod
    def on_complete(self) -> AsyncIterator[WatcherUpdate]:
        """Block until the fly scan is done.

        This is an async generator: yield a `WatcherUpdate` for each progress
        update (e.g. current position), or yield nothing if there is no
        meaningful progress to report.
        """

    async def stop(self) -> None:
        """Optional hook to stop flying and wait for everything to be stopped."""
        pass

    def with_device(self, name: str = "") -> "StandardFlyable":
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
    def velocity(self) -> float:
        """Calculate the velocity of the constant velocity phase."""
        return (self.end_position - self.start_position) / self.time_for_move

    def ramp_up_start_pos(self, acceleration_time: float) -> float:
        """Calculate the start position with run-up distance added on."""
        return self.start_position - acceleration_time * self.velocity / 2

    def ramp_down_end_pos(self, acceleration_time: float) -> float:
        """Calculate the end position with run-down distance added on."""
        return self.end_position + acceleration_time * self.velocity / 2


class StandardFlyable(
    Device,
    Stageable,
    Preparable,
    Flyable,
    Generic[T],
):
    """Device that provides standard logic for flying.

    This class must be inherited and have a `flyable_logic` @cached_property.
    For an ephemeral flyer in a plan, call `FlyableLogic.with_device` instead of
    inheriting.
    """

    @cached_property
    @abstractmethod
    def flyable_logic(self) -> FlyableLogic[T]:
        """The logic object that describes how this device flies.

        Subclasses must implement this as a `@cached_property` that returns a
        `FlyableLogic` instance.
        """

    @AsyncStatus.wrap
    async def stage(self) -> None:
        await self.unstage()

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        await self.flyable_logic.stop()

    @AsyncStatus.wrap
    async def prepare(self, value: T) -> None:
        """Move to the start and set up the fly scan."""
        await self.flyable_logic.on_prepare(value)

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        """Start the fly scan."""
        await self.flyable_logic.on_kickoff()

    @WatchableAsyncStatus.wrap
    async def complete(self) -> AsyncIterator[WatcherUpdate]:
        """Block until the fly scan is done, forwarding any progress updates."""
        async for update in self.flyable_logic.on_complete():
            yield update


class _EphemeralFlyable(StandardFlyable[T]):
    """A concrete `StandardFlyable` wrapping a given `FlyableLogic`.

    Created by `FlyableLogic.with_device` so a bare logic object can be used as
    a flyer in a plan without defining a Device subclass.
    """

    def __init__(self, flyable_logic: FlyableLogic[T], name: str = "") -> None:
        self._flyable_logic = flyable_logic
        super().__init__(name=name)

    @cached_property
    def flyable_logic(self) -> FlyableLogic[T]:
        return self._flyable_logic
