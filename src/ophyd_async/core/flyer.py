import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import (
    AsyncIterator,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Sequence,
    TypeVar,
)

from bluesky.protocols import (
    Asset,
    Collectable,
    Descriptor,
    Flyable,
    Movable,
    Reading,
    Stageable,
    WritesExternalAssets,
)

from .async_status import AsyncStatus
from .detector import DetectorControl, DetectorTrigger, DetectorWriter
from .device import Device
from .signal import SignalR
from .utils import gather_list, merge_gathered_dicts

T = TypeVar("T")


@dataclass(frozen=True)
class TriggerInfo:
    #: Number of triggers that will be sent
    num: int
    #: Sort of triggers that will be sent
    trigger: DetectorTrigger
    #: What is the minimum deadtime between triggers
    deadtime: float
    #: What is the maximum high time of the triggers
    livetime: float


class DetectorGroupLogic(ABC):
    # Read multipliers here, exposure is set in the plan
    @abstractmethod
    async def open(self) -> Dict[str, Descriptor]:
        """Open all writers, wait for them to be open and return their descriptors"""

    @abstractmethod
    async def ensure_armed(self, trigger_info: TriggerInfo):
        """Ensure the detectors are armed, return AsyncStatus that waits for disarm."""

    @abstractmethod
    def collect_asset_docs(self) -> AsyncIterator[Asset]:
        """Collect asset docs from all writers"""

    @abstractmethod
    async def wait_for_index(self, index: int):
        """Wait until a specific index is ready to be collected"""

    @abstractmethod
    async def disarm(self):
        """Disarm detectors"""

    @abstractmethod
    async def close(self):
        """Close all writers and wait for them to be closed"""


class SameTriggerDetectorGroupLogic(DetectorGroupLogic):
    def __init__(
        self,
        controllers: Sequence[DetectorControl],
        writers: Sequence[DetectorWriter],
    ) -> None:
        self.controllers = controllers
        self.writers = writers
        self._arm_statuses: Sequence[AsyncStatus] = ()
        self._trigger_info: Optional[TriggerInfo] = None

    async def open(self) -> Dict[str, Descriptor]:
        return await merge_gathered_dicts(writer.open() for writer in self.writers)

    async def ensure_armed(self, trigger_info: TriggerInfo):
        if (
            not self._arm_statuses
            or any(status.done for status in self._arm_statuses)
            or trigger_info != self._trigger_info
        ):
            # We need to re-arm
            await gather_list(controller.disarm() for controller in self.controllers)
            await gather_list(self._arm_statuses)
            for controller in self.controllers:
                required = controller.get_deadtime(trigger_info.livetime)
                assert required >= trigger_info.deadtime, (
                    f"Detector {controller} needs at least {required}s deadtime, "
                    f"but trigger logic provides only {trigger_info.deadtime}s"
                )
            self._arm_statuses = await gather_list(
                controller.arm(
                    trigger=trigger_info.trigger, exposure=trigger_info.livetime
                )
                for controller in self.controllers
            )
            self._trigger_info = trigger_info

    async def collect_asset_docs(self) -> AsyncIterator[Asset]:
        # the below is confusing: gather_list does return an awaitable, but it itself
        # is a coroutine so we must call await twice...
        indices_written = min(
            await gather_list(writer.get_indices_written() for writer in self.writers)
        )
        for writer in self.writers:
            async for doc in writer.collect_stream_docs(indices_written):
                yield doc

    async def wait_for_index(self, index: int):
        await gather_list(writer.wait_for_index(index) for writer in self.writers)

    async def disarm(self):
        await gather_list(controller.disarm() for controller in self.controllers)

    async def close(self):
        await gather_list(writer.close() for writer in self.writers)


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
    Device, Movable, Stageable, Flyable, Collectable, WritesExternalAssets, Generic[T]
):
    def __init__(
        self,
        detector_group_logic: DetectorGroupLogic,
        trigger_logic: TriggerLogic[T],
        configuration_signals: Sequence[SignalR],
        name: str = "",
    ):
        self._detector_group_logic = detector_group_logic
        self._trigger_logic = trigger_logic
        self._configuration_signals = tuple(configuration_signals)
        self._describe: Dict[str, Descriptor] = {}
        self._watchers: List[Callable] = []
        self._fly_status: Optional[AsyncStatus] = None
        self._fly_start = 0.0
        self._offset = 0  # Add this to index to get frame number
        self._current_frame = 0  # The current frame we are on
        self._last_frame = 0  # The last frame that will be emitted
        super().__init__(name=name)

    @AsyncStatus.wrap
    async def stage(self) -> None:
        await self.unstage()
        self._describe = await self._detector_group_logic.open()
        self._offset = 0
        self._current_frame = 0

    def set(self, value: T) -> AsyncStatus:
        """Arm detectors and setup trajectories"""
        # index + offset = current_frame, but starting a new scan so want it to be 0
        # so subtract current_frame from both sides
        return AsyncStatus(self._set(value))

    async def _set(self, value: T) -> None:
        self._offset -= self._current_frame
        self._current_frame = 0
        await self._prepare(value)

    async def _prepare(self, value: T):
        trigger_info = self._trigger_logic.trigger_info(value)
        # Move to start and setup the flyscan, and arm dets in parallel
        await asyncio.gather(
            self._detector_group_logic.ensure_armed(trigger_info),
            self._trigger_logic.prepare(value),
        )
        self._last_frame = self._current_frame + trigger_info.num

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

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        self._watchers = []
        self._fly_status = AsyncStatus(self._fly(), self._watchers)
        self._fly_start = time.monotonic()

    async def _fly(self) -> None:
        await self._trigger_logic.start()
        # Wait for all detectors to have written up to a particular frame
        await self._detector_group_logic.wait_for_index(self._last_frame - self._offset)

    async def collect_asset_docs(self) -> AsyncIterator[Asset]:
        current_frame = self._current_frame
        async for asset in self._detector_group_logic.collect_asset_docs():
            name, doc = asset
            if name == "stream_datum":
                current_frame = doc["indices"]["stop"] + self._offset
            yield asset
        if current_frame != self._current_frame:
            self._current_frame = current_frame
            for watcher in self._watchers:
                watcher(
                    name=self.name,
                    current=current_frame,
                    initial=0,
                    target=self._last_frame,
                    unit="",
                    precision=0,
                    time_elapsed=time.monotonic() - self._fly_start,
                )

    def complete(self) -> AsyncStatus:
        assert self._fly_status, "Kickoff not run"
        return self._fly_status

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        await asyncio.gather(
            self._trigger_logic.stop(),
            self._detector_group_logic.close(),
            self._detector_group_logic.disarm(),
        )
