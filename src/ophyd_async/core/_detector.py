"""Module which defines abstract classes to work with detectors"""

import asyncio
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import (
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Sequence,
)

from bluesky.protocols import (
    Collectable,
    DataKey,
    Flyable,
    Preparable,
    Reading,
    Stageable,
    StreamAsset,
    Triggerable,
    WritesStreamAssets,
)
from pydantic import BaseModel, Field

from ._device import Device
from ._protocol import AsyncConfigurable, AsyncReadable
from ._status import AsyncStatus, WatchableAsyncStatus
from ._utils import DEFAULT_TIMEOUT, T, WatcherUpdate, merge_gathered_dicts


class DetectorTrigger(str, Enum):
    """Type of mechanism for triggering a detector to take frames"""

    #: Detector generates internal trigger for given rate
    internal = "internal"
    #: Expect a series of arbitrary length trigger signals
    edge_trigger = "edge_trigger"
    #: Expect a series of constant width external gate signals
    constant_gate = "constant_gate"
    #: Expect a series of variable width external gate signals
    variable_gate = "variable_gate"


class TriggerInfo(BaseModel):
    """Minimal set of information required to setup triggering on a detector"""

    #: Number of triggers that will be sent, 0 means infinite
    number: int = Field(gt=0)
    #: Sort of triggers that will be sent
    trigger: DetectorTrigger = Field()
    #: What is the minimum deadtime between triggers
    deadtime: float = Field(ge=0)
    #: What is the maximum high time of the triggers
    livetime: float = Field(ge=0)
    #: What is the maximum timeout on waiting for a frame
    frame_timeout: float | None = Field(None, gt=0)


class DetectorControl(ABC):
    """
    Classes implementing this interface should hold the logic for
    arming and disarming a detector
    """

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
        """
        Arm detector, do all necessary steps to prepare detector for triggers.

        Args:
            num: Expected number of frames
            trigger: Type of trigger for which to prepare the detector. Defaults to
            DetectorTrigger.internal.
            exposure: Exposure time with which to set up the detector. Defaults to None
            if not applicable or the detector is expected to use its previously-set
            exposure time.

        Returns:
            AsyncStatus: Status representing the arm operation. This function returning
            represents the start of the arm. The returned status completing means
            the detector is now armed.
        """

    @abstractmethod
    async def disarm(self):
        """Disarm the detector, return detector to an idle state"""


class DetectorWriter(ABC):
    """Logic for making a detector write data to somewhere persistent
    (e.g. an HDF5 file)"""

    @abstractmethod
    async def open(self, multiplier: int = 1) -> Dict[str, DataKey]:
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
        """Yield the index of each frame (or equivalent data point) as it is written"""

    @abstractmethod
    async def get_indices_written(self) -> int:
        """Get the number of indices written"""

    @abstractmethod
    def collect_stream_docs(self, indices_written: int) -> AsyncIterator[StreamAsset]:
        """Create Stream docs up to given number written"""

    @abstractmethod
    async def close(self) -> None:
        """Close writer, blocks until I/O is complete"""


class StandardDetector(
    Device,
    Stageable,
    AsyncConfigurable,
    AsyncReadable,
    Triggerable,
    Preparable,
    Flyable,
    Collectable,
    WritesStreamAssets,
    Generic[T],
):
    """
    Useful detector base class for step and fly scanning detectors.
    Aggregates controller and writer logic together.
    """

    def __init__(
        self,
        controller: DetectorControl,
        writer: DetectorWriter,
        config_sigs: Sequence[AsyncReadable] = (),
        name: str = "",
    ) -> None:
        """
        Constructor

        Args:
            controller: Logic for arming and disarming the detector
            writer: Logic for making the detector write persistent data
            config_sigs: Signals to read when describe and read
            configuration are called. Defaults to ().
            name: Device name. Defaults to "".
        """
        self._controller = controller
        self._writer = writer
        self._describe: Dict[str, DataKey] = {}
        self._config_sigs = list(config_sigs)
        # For prepare
        self._arm_status: Optional[AsyncStatus] = None
        self._trigger_info: Optional[TriggerInfo] = None
        # For kickoff
        self._watchers: List[Callable] = []
        self._fly_status: Optional[WatchableAsyncStatus] = None
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
        # Disarm the detector, stop filewriting, and open file for writing.
        await self._check_config_sigs()
        await asyncio.gather(self.writer.close(), self.controller.disarm())
        self._describe = await self.writer.open()

    async def _check_config_sigs(self):
        """Checks configuration signals are named and connected."""
        for signal in self._config_sigs:
            if signal.name == "":
                raise Exception(
                    "config signal must be named before it is passed to the detector"
                )
            try:
                await signal.get_value()
            except NotImplementedError:
                raise Exception(
                    f"config signal {signal.name} must be connected before it is "
                    + "passed to the detector"
                )

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        # Stop data writing.
        await self.writer.close()

    async def read_configuration(self) -> Dict[str, Reading]:
        return await merge_gathered_dicts(sig.read() for sig in self._config_sigs)

    async def describe_configuration(self) -> Dict[str, DataKey]:
        return await merge_gathered_dicts(sig.describe() for sig in self._config_sigs)

    async def read(self) -> Dict[str, Reading]:
        # All data is in StreamResources, not Events, so nothing to output here
        return {}

    async def describe(self) -> Dict[str, DataKey]:
        return self._describe

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        # set default trigger_info
        self._trigger_info = TriggerInfo(
            number=1, trigger=DetectorTrigger.internal, deadtime=0.0, livetime=0.0
        )
        # Arm the detector and wait for it to finish.
        indices_written = await self.writer.get_indices_written()
        written_status = await self.controller.arm(
            num=self._trigger_info.number,
            trigger=self._trigger_info.trigger,
        )
        await written_status
        end_observation = indices_written + 1

        async for index in self.writer.observe_indices_written(
            DEFAULT_TIMEOUT + self._trigger_info.livetime + self._trigger_info.deadtime
        ):
            if index >= end_observation:
                break

    def prepare(
        self,
        value: T,
    ) -> AsyncStatus:
        # Just arm detector for the time being
        return AsyncStatus(self._prepare(value))

    async def _prepare(self, value: T) -> None:
        """
        Arm detector.

        Prepare the detector with trigger information. This is determined at and passed
        in from the plan level.

        This currently only prepares detectors for flyscans and stepscans just use the
        trigger information determined in trigger.

        To do: Unify prepare to be use for both fly and step scans.

        Args:
            value: TriggerInfo describing how to trigger the detector
        """
        assert type(value) is TriggerInfo
        self._trigger_info = value
        self._initial_frame = await self.writer.get_indices_written()
        self._last_frame = self._initial_frame + self._trigger_info.number

        required = self.controller.get_deadtime(self._trigger_info.livetime)
        assert required <= self._trigger_info.deadtime, (
            f"Detector {self.controller} needs at least {required}s deadtime, "
            f"but trigger logic provides only {self._trigger_info.deadtime}s"
        )
        self._arm_status = await self.controller.arm(
            num=self._trigger_info.number,
            trigger=self._trigger_info.trigger,
            exposure=self._trigger_info.livetime,
        )
        self._fly_start = time.monotonic()

    @AsyncStatus.wrap
    async def kickoff(self):
        if not self._arm_status:
            raise Exception("Detector not armed!")

    @WatchableAsyncStatus.wrap
    async def complete(self):
        assert self._arm_status, "Prepare not run"
        assert self._trigger_info
        async for index in self.writer.observe_indices_written(
            self._trigger_info.frame_timeout
            or (
                DEFAULT_TIMEOUT
                + self._trigger_info.livetime
                + self._trigger_info.deadtime
            )
        ):
            yield WatcherUpdate(
                name=self.name,
                current=index,
                initial=self._initial_frame,
                target=self._trigger_info.number,
                unit="",
                precision=0,
                time_elapsed=time.monotonic() - self._fly_start,
            )
            if index >= self._trigger_info.number:
                break

    async def describe_collect(self) -> Dict[str, DataKey]:
        return self._describe

    async def collect_asset_docs(
        self, index: Optional[int] = None
    ) -> AsyncIterator[StreamAsset]:
        # Collect stream datum documents for all indices written.
        # The index is optional, and provided for fly scans, however this needs to be
        # retrieved for step scans.
        if index is None:
            index = await self.writer.get_indices_written()
        async for doc in self.writer.collect_stream_docs(index):
            yield doc

    async def get_index(self) -> int:
        return await self.writer.get_indices_written()
