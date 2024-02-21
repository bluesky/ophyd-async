from abc import ABC, abstractmethod
from typing import Dict, Generic, Optional, Sequence, TypeVar

from bluesky.protocols import Descriptor, Flyable, Preparable, Reading, Stageable

from .async_status import AsyncStatus
from .detector import TriggerInfo
from .device import Device
from .signal import SignalR
from .utils import merge_gathered_dicts

T = TypeVar("T")


class TriggerLogic(ABC, Generic[T]):
    @abstractmethod
    def trigger_info(self, value: T) -> TriggerInfo:
        """Return info about triggers that will be produced for a given value"""

    @abstractmethod
    async def prepare(self, value: T):
        """Move to the start of the flyscan"""

    @abstractmethod
    async def start(self):
        """Start the flyscan"""

    @abstractmethod
    async def stop(self):
        """Stop flying and wait everything to be stopped"""


class HardwareTriggeredFlyable(
    Device,
    Stageable,
    Preparable,
    Flyable,
    Generic[T],
):
    def __init__(
        self,
        trigger_logic: TriggerLogic[T],
        configuration_signals: Sequence[SignalR],
        name: str = "",
    ):
        self._trigger_logic = trigger_logic
        self._configuration_signals = tuple(configuration_signals)
        self._describe: Dict[str, Descriptor] = {}
        self._fly_status: Optional[AsyncStatus] = None
        self._trigger_info: Optional[TriggerInfo] = None
        super().__init__(name=name)

    @property
    def trigger_logic(self) -> TriggerLogic[T]:
        return self._trigger_logic

    @property
    def trigger_info(self) -> Optional[TriggerInfo]:
        return self._trigger_info

    @AsyncStatus.wrap
    async def stage(self) -> None:
        await self.unstage()

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        await self._trigger_logic.stop()

    def prepare(self, value: T) -> AsyncStatus:
        """Setup trajectories"""
        return AsyncStatus(self._prepare(value))

    async def _prepare(self, value: T) -> None:
        self._trigger_info = self._trigger_logic.trigger_info(value)
        # Move to start and setup the flyscan
        await self._trigger_logic.prepare(value)

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        self._fly_status = AsyncStatus(self._trigger_logic.start())

    def complete(self) -> AsyncStatus:
        assert self._fly_status, "Kickoff not run"
        return self._fly_status

    async def describe_configuration(self) -> Dict[str, Descriptor]:
        return await merge_gathered_dicts(
            [sig.describe() for sig in self._configuration_signals]
        )

    async def read_configuration(self) -> Dict[str, Reading]:
        return await merge_gathered_dicts(
            [sig.read() for sig in self._configuration_signals]
        )
