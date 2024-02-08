from abc import ABC, abstractmethod
from typing import Dict, Generic, Optional, Sequence, TypeVar

from bluesky.protocols import (
    Collectable,
    Descriptor,
    Flyable,
    HasHints,
    Hints,
    Preparable,
    Reading,
    Stageable,
)

from .async_status import AsyncStatus
from .detector import DetectorControl, DetectorWriter, TriggerInfo
from .device import Device
from .signal import SignalR
from .utils import DEFAULT_TIMEOUT, gather_list, merge_gathered_dicts

T = TypeVar("T")


class DetectorGroupLogic(ABC):
    # Read multipliers here, exposure is set in the plan

    @abstractmethod
    async def open(self) -> Dict[str, Descriptor]:
        """Open all writers, wait for them to be open and return their descriptors"""

    @abstractmethod
    async def ensure_armed(self, trigger_info: TriggerInfo):
        """Ensure the detectors are armed, return AsyncStatus that waits for disarm."""

    @abstractmethod
    async def wait_for_index(
        self, index: int, timeout: Optional[float] = DEFAULT_TIMEOUT
    ):
        """Wait until a specific index is ready to be collected"""

    @abstractmethod
    async def disarm(self):
        """Disarm detectors"""

    @abstractmethod
    async def close(self):
        """Close all writers and wait for them to be closed"""

    @abstractmethod
    def hints(self) -> Hints:
        """Produce hints specifying which dataset(s) are most important"""


class SameTriggerDetectorGroupLogic(DetectorGroupLogic):
    def __init__(
        self,
        controllers: Sequence[DetectorControl],
        writers: Sequence[DetectorWriter],
    ) -> None:
        self._controllers = controllers
        self._writers = writers
        self._arm_statuses: Sequence[AsyncStatus] = ()
        self._trigger_info: Optional[TriggerInfo] = None

    async def open(self) -> Dict[str, Descriptor]:
        return await merge_gathered_dicts(writer.open() for writer in self._writers)

    async def ensure_armed(self, trigger_info: TriggerInfo):
        ...

    async def wait_for_index(
        self, index: int, timeout: Optional[float] = DEFAULT_TIMEOUT
    ):
        await gather_list(
            writer.wait_for_index(index, timeout=timeout) for writer in self._writers
        )

    async def disarm(self):
        await gather_list(controller.disarm() for controller in self._controllers)
        await gather_list(self._arm_statuses)

    async def close(self):
        await gather_list(writer.close() for writer in self._writers)

    def hints(self) -> Hints:
        return {
            "fields": [
                field
                for writer in self._writers
                if hasattr(writer, "hints")
                for field in writer.hints.get("fields")
            ]
        }


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
    Preparable,
    Stageable,
    Flyable,
    Collectable,
    HasHints,
    Generic[T],
):
    def __init__(
        self,
        trigger_logic: TriggerLogic[T],
        configuration_signals: Sequence[SignalR],
        trigger_to_frame_timeout: Optional[float] = DEFAULT_TIMEOUT,
        name: str = "",
    ):
        self._trigger_logic = trigger_logic
        self._configuration_signals = tuple(configuration_signals)
        self._describe: Dict[str, Descriptor] = {}
        self._fly_status: Optional[AsyncStatus] = None
        self._trigger_info: Optional[TriggerInfo] = None
        super().__init__(name=name)

    @property
    def hints(self) -> Hints:
        return self._detector_group_logic.hints()

    @property
    def trigger_logic(self) -> TriggerLogic[T]:
        return self._trigger_logic

    @property
    def trigger_info(self) -> TriggerInfo:
        return self._trigger_info

    @AsyncStatus.wrap
    async def stage(self) -> None:
        await self.unstage()

    def prepare(self, value: T) -> AsyncStatus:
        """Setup trajectories"""
        return AsyncStatus(self._prepare(value))

    async def _prepare(self, value: T) -> None:
        self._trigger_info = self._trigger_logic.trigger_info(value)
        # Move to start and setup the flyscan
        await self._trigger_logic.prepare(value)

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        self._fly_status = AsyncStatus(await self._trigger_logic.start())

    def complete(self) -> AsyncStatus:
        assert self._fly_status, "Kickoff not run"
        return self._fly_status

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        await self._trigger_logic.stop()

    async def describe_configuration(self) -> Dict[str, Descriptor]:
        return await merge_gathered_dicts(
            [sig.describe() for sig in self._configuration_signals]
        )

    async def read_configuration(self) -> Dict[str, Reading]:
        return await merge_gathered_dicts(
            [sig.read() for sig in self._configuration_signals]
        )

    async def describe_collect(self) -> Dict[str, Descriptor]:
        return self._describe
