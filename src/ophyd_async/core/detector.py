"""Module which defines abstract classes to work with detectors"""

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Callable, Dict, List, Optional, Sequence, TypeVar

from bluesky.protocols import (
    Asset,
    Collectable,
    Configurable,
    Descriptor,
    Readable,
    Reading,
    Stageable,
    StreamAsset,
    Triggerable,
    WritesStreamAssets,
)

from .async_status import AsyncStatus
from .device import Device
from .signal import SignalR
from .utils import DEFAULT_TIMEOUT, merge_gathered_dicts

T = TypeVar("T")


class DetectorTrigger(str, Enum):
    #: Detector generates internal trigger for given rate
    internal = "internal"
    #: Expect a series of arbitrary length trigger signals
    edge_trigger = "edge_trigger"
    #: Expect a series of constant width external gate signals
    constant_gate = "constant_gate"
    #: Expect a series of variable width external gate signals
    variable_gate = "variable_gate"


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


class DetectorControl(ABC):
    @abstractmethod
    def get_deadtime(self, exposure: float) -> float:
        """For a given exposure, how long should the time between exposures be"""

    @abstractmethod
    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        """Arm the detector and return AsyncStatus.

        Awaiting the return value will wait for num frames to be written.
        """

    @abstractmethod
    async def disarm(self):
        """Disarm the detector"""


class DetectorWriter(ABC):
    @abstractmethod
    async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        """Open writer and wait for it to be ready for data.

        Args:
            multiplier: Each StreamDatum index corresponds to this many
                written exposures

        Returns:
            Output for ``describe()``
        """

    @abstractmethod
    async def wait_for_index(
        self, index: int, timeout: Optional[float] = DEFAULT_TIMEOUT
    ) -> None:
        """Wait until a specific index is ready to be collected"""

    @abstractmethod
    async def get_indices_written(self) -> int:
        """Get the number of indices written"""

    @abstractmethod
    def collect_stream_docs(self, indices_written: int) -> AsyncIterator[Asset]:
        """Create Stream docs up to given number written"""

    @abstractmethod
    async def close(self) -> None:
        """Close writer and wait for it to be finished"""


class StandardDetector(
    Device,
    Stageable,
    Configurable,
    Readable,
    Triggerable,
    WritesStreamAssets,
    Collectable,
):
    """Detector with useful default behaviour.

    Must be supplied instances of classes that inherit from DetectorControl and
    DetectorData, to dictate how the detector will be controlled (i.e. arming and
    disarming) as well as how the detector data will be written (i.e. opening and
    closing the writer, and handling data writing indices).

    NOTE: only for step-scans.
    """

    def __init__(
        self,
        controller: DetectorControl,
        writer: DetectorWriter,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
        writer_timeout: float = DEFAULT_TIMEOUT,
        trigger_to_frame_timeout: Optional[float] = DEFAULT_TIMEOUT,
    ) -> None:
        """
        Parameters
        ----------
        control:
            instance of class which inherits from :class:`DetectorControl`
        data:
            instance of class which inherits from :class:`DetectorData`
        name:
            detector name
        """
        self._controller = controller
        self._writer = writer
        self._describe: Dict[str, Descriptor] = {}
        self._config_sigs = list(config_sigs)
        self._frame_writing_timeout = writer_timeout
        # Is this unique from the frame_writing_timeout?
        self._trigger_to_frame_timeout = trigger_to_frame_timeout
        # For prepare
        self._arm_status: Optional[AsyncStatus] = None
        self._trigger_info: Optional[TriggerInfo] = None
        # For kickoff
        self._watcher: List[Callable] = []
        self._fly_status: Optional[AsyncStatus] = None

        self._offset = 0  # Add this to index to get frame number
        self._current_frame = 0  # The current frame we are on
        self._last_frame = 0  # The last frame that will be emitted

        super().__init__(name)

    @property
    def controller(self) -> DetectorControl:
        return self._controller

    @property
    def writer(self) -> DetectorWriter:
        return self._writer

    @AsyncStatus.wrap
    async def stage(self) -> None:
        """Disarm the detector, stop filewriting, and open file for writing."""
        await self.check_config_sigs()
        await asyncio.gather(self.writer.close(), self.controller.disarm())
        self._describe = await self.writer.open()

        self._current_frame = 0  # do we care about this?

    def prepare(
        self,
        value: T,
        current_frame=None,
        last_frame=None,
    ) -> AsyncStatus:
        """Arm detectors"""
        return AsyncStatus(self._prepare(value, current_frame, last_frame))

    async def _prepare(self, value: T, current_frame, last_frame) -> None:
        """Arm detectors,

        The frame information was managed in the flyer and now needs to be
        managed in the plan level.
        """
        assert type(value) is TriggerInfo
        self._trigger_info = value
        self._current_frame = current_frame
        self._last_frame = last_frame

        self._current_frame = 0
        self._last_frame = self._current_frame + self._trigger_info.num

        await self.ensure_armed(self._trigger_info)

    async def ensure_armed(self, trigger_info: TriggerInfo):
        if (
            not self._arm_status
            or self._arm_status.done
            or trigger_info != self._trigger_info
        ):
            # we need to re-arm
            await self.controller.disarm()
            required = self.controller.get_deadtime(trigger_info.livetime)
            assert required <= trigger_info.deadtime, (
                f"Detector {self.controller} needs at least {required}s deadtime, "
                f"but trigger logic provides only {trigger_info.deadtime}s"
            )
            self._arm_status = await self.controller.arm(
                num=trigger_info.num,
                trigger=trigger_info.trigger,
                exposure=trigger_info.livetime,
            )

    async def check_config_sigs(self):
        """Checks configuration signals are named and connected."""
        for signal in self._config_sigs:
            if signal._name == "":
                raise Exception(
                    "config signal must be named before it is passed to the detector"
                )
            try:
                await signal.get_value()
            except NotImplementedError:
                raise Exception(
                    f"config signal {signal._name} must be connected before it is "
                    + "passed to the detector"
                )

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        self._fly_status = AsyncStatus(self._fly(), self._watcher)
        self._fly_start = time.monotonic()  # do we care about this?

    async def _fly(self) -> None:
        # Wait for detector to have written up to a particular frame
        await self.writer.wait_for_index(
            self._last_frame - self._offset, timeout=self._trigger_to_frame_timeout
        )

    @AsyncStatus.wrap
    async def complete(self) -> AsyncStatus:
        assert self._fly_status, "Kickoff not run"
        return self._fly_status

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        """Stop data writing."""
        await self.writer.close()

    async def describe_configuration(self) -> Dict[str, Descriptor]:
        return await merge_gathered_dicts(sig.describe() for sig in self._config_sigs)

    async def read_configuration(self) -> Dict[str, Reading]:
        return await merge_gathered_dicts(sig.read() for sig in self._config_sigs)

    def describe(self) -> Dict[str, Descriptor]:
        return self._describe

    async def describe_collect(self) -> Dict[str, Descriptor]:
        return self._describe

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        """Arm the detector and wait for it to finish."""
        indices_written = await self.writer.get_indices_written()
        written_status = await self.controller.arm(
            num=1,
            trigger=DetectorTrigger.internal,
        )
        await written_status
        await self.writer.wait_for_index(
            indices_written + 1, timeout=self._frame_writing_timeout
        )

    async def read(self) -> Dict[str, Reading]:
        """Read the detector"""
        # All data is in StreamResources, not Events, so nothing to output here
        return {}

    async def get_index(self) -> int:
        return await self.writer.get_indices_written()

    async def collect_asset_docs(
        self, index: Optional[int]
    ) -> AsyncIterator[StreamAsset]:
        """Collect stream datum documents for all indices written.

        The index is optional, and provided for flyscans, however this needs to be
        retrieved for stepscans.
        """
        if index:
            async for doc in self.writer.collect_stream_docs(index):
                yield doc
        else:
            index = await self.writer.get_indices_written()
            async for doc in self.writer.collect_stream_docs(index):
                yield doc
