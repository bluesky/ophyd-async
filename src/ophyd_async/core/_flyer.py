from abc import ABC, abstractmethod
from typing import Any, Generic

from bluesky.protocols import Flyable, Preparable, Stageable
from pydantic import Field

from ._device import Device
from ._status import AsyncStatus
from ._utils import CALCULATE_TIMEOUT, CalculatableTimeout, ConfinedModel, T


class FlyerController(ABC, Generic[T]):
    """Base class for controlling 'flyable' devices.

    [`bluesky.protocols.Flyable`](#bluesky.protocols.Flyable).
    """

    @abstractmethod
    async def prepare(self, value: T) -> Any:
        """Move to the start of the fly scan."""

    @abstractmethod
    async def kickoff(self):
        """Start the fly scan."""

    @abstractmethod
    async def complete(self):
        """Block until the fly scan is done."""

    @abstractmethod
    async def stop(self):
        """Stop flying and wait everything to be stopped."""


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


class StandardFlyer(
    Device,
    Stageable,
    Preparable,
    Flyable,
    Generic[T],
):
    """Base class for 'flyable' devices.

    [`bluesky.protocols.Flyable`](#bluesky.protocols.Flyable).
    """

    def __init__(
        self,
        trigger_logic: FlyerController[T],
        name: str = "",
    ):
        self._trigger_logic = trigger_logic
        super().__init__(name=name)

    @property
    def trigger_logic(self) -> FlyerController[T]:
        return self._trigger_logic

    @AsyncStatus.wrap
    async def stage(self) -> None:
        await self.unstage()

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        await self._trigger_logic.stop()

    def prepare(self, value: T) -> AsyncStatus:
        return AsyncStatus(self._prepare(value))

    async def _prepare(self, value: T) -> None:
        # Move to start and setup the fly scan
        await self._trigger_logic.prepare(value)

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        await self._trigger_logic.kickoff()

    @AsyncStatus.wrap
    async def complete(self) -> None:
        await self._trigger_logic.complete()
