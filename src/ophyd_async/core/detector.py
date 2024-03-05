"""Module which defines abstract classes to work with detectors"""

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import (
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    TypeVar,
)

from bluesky.protocols import (
    Collectable,
    Configurable,
    Descriptor,
    Flyable,
    Preparable,
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
    def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        """Yield each index as it is written"""

    @abstractmethod
    async def get_indices_written(self) -> int:
        """Get the number of indices written"""

    @abstractmethod
    def collect_stream_docs(self, indices_written: int) -> AsyncIterator[StreamAsset]:
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
    Preparable,
    Flyable,
    Collectable,
    WritesStreamAssets,
):
    """Detector with useful step and flyscan behaviour.

    Must be supplied instances of classes that inherit from DetectorControl and
    DetectorData, to dictate how the detector will be controlled (i.e. arming and
    disarming) as well as how the detector data will be written (i.e. opening and
    closing the writer, and handling data writing indices).

    """

    def __init__(
        self,
        controller: DetectorControl,
        writer: DetectorWriter,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
        writer_timeout: float = DEFAULT_TIMEOUT,
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
        # For prepare
        self._arm_status: Optional[AsyncStatus] = None
        self._trigger_info: Optional[TriggerInfo] = None
        # For kickoff
        self._watchers: List[Callable] = []
        self._fly_status: Optional[AsyncStatus] = None
        self._fly_start: float

        self._intial_frame: int
        self._last_frame: int
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
    async def unstage(self) -> None:
        """Stop data writing."""
        await self.writer.close()

    async def read_configuration(self) -> Dict[str, Reading]:
        return await merge_gathered_dicts(sig.read() for sig in self._config_sigs)

    async def describe_configuration(self) -> Dict[str, Descriptor]:
        return await merge_gathered_dicts(sig.describe() for sig in self._config_sigs)

    async def read(self) -> Dict[str, Reading]:
        """Read the detector"""
        # All data is in StreamResources, not Events, so nothing to output here
        return {}

    def describe(self) -> Dict[str, Descriptor]:
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
        end_observation = indices_written + 1

        async for index in self.writer.observe_indices_written(
            self._frame_writing_timeout
        ):
            if index >= end_observation:
                break

    def prepare(
        self,
        value: T,
    ) -> AsyncStatus:
        """Arm detector"""
        return AsyncStatus(self._prepare(value))

    async def _prepare(self, value: T) -> None:
        """Arm detector.

        Prepare the detector with trigger information. This is determined at and passed
        in from the plan level.

        This currently only prepares detectors for flyscans and stepscans just use the
        trigger information determined in trigger.

        To do: Unify prepare to be use for both fly and step scans.
        """
        assert type(value) is TriggerInfo
        self._trigger_info = value
        self._initial_frame = await self.writer.get_indices_written()
        self._last_frame = self._initial_frame + self._trigger_info.num

        required = self.controller.get_deadtime(self._trigger_info.livetime)
        assert required <= self._trigger_info.deadtime, (
            f"Detector {self.controller} needs at least {required}s deadtime, "
            f"but trigger logic provides only {self._trigger_info.deadtime}s"
        )

        self._arm_status = await self.controller.arm(
            num=self._trigger_info.num,
            trigger=self._trigger_info.trigger,
            exposure=self._trigger_info.livetime,
        )

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        self._fly_status = AsyncStatus(self._fly(), self._watchers)
        self._fly_start = time.monotonic()

    async def _fly(self) -> None:
        await self._observe_writer_indicies(self._last_frame)

    async def _observe_writer_indicies(self, end_observation: int):
        async for index in self.writer.observe_indices_written(
            self._frame_writing_timeout
        ):
            for watcher in self._watchers:
                watcher(
                    name=self.name,
                    current=index,
                    initial=self._initial_frame,
                    target=end_observation,
                    unit="",
                    precision=0,
                    time_elapsed=time.monotonic() - self._fly_start,
                )
            if index >= end_observation:
                break

    @AsyncStatus.wrap
    async def complete(self) -> AsyncStatus:
        assert self._fly_status, "Kickoff not run"
        return await self._fly_status

    async def describe_collect(self) -> Dict[str, Descriptor]:
        return self._describe

    async def collect_asset_docs(
        self, index: Optional[int] = None
    ) -> AsyncIterator[StreamAsset]:
        """Collect stream datum documents for all indices written.

        The index is optional, and provided for flyscans, however this needs to be
        retrieved for stepscans.
        """
        if not index:
            index = await self.writer.get_indices_written()
        async for doc in self.writer.collect_stream_docs(index):
            yield doc

    async def get_index(self) -> int:
        return await self.writer.get_indices_written()
