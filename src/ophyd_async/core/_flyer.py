from abc import ABC, abstractmethod
from typing import Any, Generic

from bluesky.protocols import Flyable, Preparable, Stageable

from ._device import Device
from ._status import AsyncStatus
from ._utils import T


class FlyerController(ABC, Generic[T]):
    """Base class for controlling 'flyable' devices.

    [`bluesky.protocols.Flyable`](#bluesky.protocols.Flyable).
    """

    @abstractmethod
    async def prepare(self, value: T) -> Any:
        """Move to the start of the flyscan."""

    @abstractmethod
    async def kickoff(self):
        """Start the flyscan."""

    @abstractmethod
    async def complete(self):
        """Block until the flyscan is done."""

    @abstractmethod
    async def stop(self):
        """Stop flying and wait everything to be stopped."""


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
        # Move to start and setup the flyscan
        await self._trigger_logic.prepare(value)

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        await self._trigger_logic.kickoff()

    @AsyncStatus.wrap
    async def complete(self) -> None:
        await self._trigger_logic.complete()
