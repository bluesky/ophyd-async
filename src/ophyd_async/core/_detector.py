"""Module which defines abstract classes to work with detectors"""

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator, Sequence
from enum import Enum
from functools import cached_property
from typing import (
    Generic,
)

from bluesky.protocols import (
    Collectable,
    Flyable,
    Preparable,
    Reading,
    Stageable,
    StreamAsset,
    Triggerable,
    WritesStreamAssets,
)
from event_model import DataKey
from pydantic import BaseModel, Field, NonNegativeInt, computed_field

from ._device import Device
from ._protocol import AsyncConfigurable, AsyncReadable
from ._signal import SignalR
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

    #: Number of triggers that will be sent, (0 means infinite) Can be:
    #  - A single integer or
    #  - A list of integers for multiple triggers
    # Example for tomography: TriggerInfo(number=[2,3,100,3])
    #:     This would trigger:
    #:     - 2 times for dark field images
    #:     - 3 times for initial flat field images
    #:     - 100 times for projections
    #:     - 3 times for final flat field images
    number_of_triggers: NonNegativeInt | list[NonNegativeInt]
    #: Sort of triggers that will be sent
    trigger: DetectorTrigger = Field(default=DetectorTrigger.internal)
    #: What is the minimum deadtime between triggers
    deadtime: float | None = Field(default=None, ge=0)
    #: What is the maximum high time of the triggers
    livetime: float | None = Field(default=None, ge=0)
    #: What is the maximum timeout on waiting for a frame
    frame_timeout: float | None = Field(default=None, gt=0)
    #: How many triggers make up a single StreamDatum index, to allow multiple frames
    #: from a faster detector to be zipped with a single frame from a slow detector
    #: e.g. if num=10 and multiplier=5 then the detector will take 10 frames,
    #: but publish 2 indices, and describe() will show a shape of (5, h, w)
    multiplier: int = 1

    @computed_field
    @cached_property
    def total_number_of_triggers(self) -> int:
        return (
            sum(self.number_of_triggers)
            if isinstance(self.number_of_triggers, list)
            else self.number_of_triggers
        )


class DetectorController(ABC):
    """
    Classes implementing this interface should hold the logic for
    arming and disarming a detector
    """

    @abstractmethod
    def get_deadtime(self, exposure: float | None) -> float:
        """For a given exposure, how long should the time between exposures be"""

    @abstractmethod
    async def prepare(self, trigger_info: TriggerInfo):
        """
        Do all necessary steps to prepare the detector for triggers.

        Args:
            trigger_info: This is a Pydantic model which contains
                number Expected number of frames.
                trigger Type of trigger for which to prepare the detector. Defaults
                to DetectorTrigger.internal.
                livetime Livetime / Exposure time with which to set up the detector.
                Defaults to None
                if not applicable or the detector is expected to use its previously-set
                exposure time.
                deadtime Defaults to None. This is the minimum deadtime between
                triggers.
                multiplier The number of triggers grouped into a single StreamDatum
                index.
        """

    @abstractmethod
    async def arm(self) -> None:
        """
        Arm the detector
        """

    @abstractmethod
    async def wait_for_idle(self):
        """
        This will wait on the internal _arm_status and wait for it to get disarmed/idle
        """

    @abstractmethod
    async def disarm(self):
        """Disarm the detector, return detector to an idle state"""


class DetectorWriter(ABC):
    """Logic for making a detector write data to somewhere persistent
    (e.g. an HDF5 file)"""

    @abstractmethod
    async def open(self, multiplier: int = 1) -> dict[str, DataKey]:
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
        controller: DetectorController,
        writer: DetectorWriter,
        config_sigs: Sequence[SignalR] = (),
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
        self._describe: dict[str, DataKey] = {}
        self._config_sigs = list(config_sigs)
        # For prepare
        self._arm_status: AsyncStatus | None = None
        self._trigger_info: TriggerInfo | None = None
        # For kickoff
        self._watchers: list[Callable] = []
        self._fly_status: WatchableAsyncStatus | None = None
        self._fly_start: float | None = None
        self._frames_to_complete: int = 0
        # Represents the total number of frames that will have been completed at the
        # end of the next `complete`.
        self._completable_frames: int = 0
        self._number_of_triggers_iter: Iterator[int] | None = None
        self._initial_frame: int = 0

        super().__init__(name)

    @property
    def controller(self) -> DetectorController:
        return self._controller

    @property
    def writer(self) -> DetectorWriter:
        return self._writer

    @AsyncStatus.wrap
    async def stage(self) -> None:
        # Disarm the detector, stop file writing.
        await self._check_config_sigs()
        await asyncio.gather(self.writer.close(), self.controller.disarm())
        self._trigger_info = None

    async def _check_config_sigs(self):
        """Checks configuration signals are named and connected."""
        for signal in self._config_sigs:
            if signal.name == "":
                raise Exception(
                    "config signal must be named before it is passed to the detector"
                )
            try:
                await signal.get_value()
            except NotImplementedError as e:
                raise Exception(
                    f"config signal {signal.name} must be connected before it is "
                    + "passed to the detector"
                ) from e

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        # Stop data writing.
        await asyncio.gather(self.writer.close(), self.controller.disarm())

    async def read_configuration(self) -> dict[str, Reading]:
        return await merge_gathered_dicts(sig.read() for sig in self._config_sigs)

    async def describe_configuration(self) -> dict[str, DataKey]:
        return await merge_gathered_dicts(sig.describe() for sig in self._config_sigs)

    async def read(self) -> dict[str, Reading]:
        # All data is in StreamResources, not Events, so nothing to output here
        return {}

    async def describe(self) -> dict[str, DataKey]:
        return self._describe

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        if self._trigger_info is None:
            await self.prepare(
                TriggerInfo(
                    number_of_triggers=1,
                    trigger=DetectorTrigger.internal,
                    deadtime=None,
                    livetime=None,
                    frame_timeout=None,
                )
            )
        assert self._trigger_info
        assert self._trigger_info.trigger is DetectorTrigger.internal
        # Arm the detector and wait for it to finish.
        indices_written = await self.writer.get_indices_written()
        await self.controller.arm()
        await self.controller.wait_for_idle()
        end_observation = indices_written + 1

        async for index in self.writer.observe_indices_written(
            DEFAULT_TIMEOUT
            + (self._trigger_info.livetime or 0)
            + (self._trigger_info.deadtime or 0)
        ):
            if index >= end_observation:
                break

    @AsyncStatus.wrap
    async def prepare(self, value: TriggerInfo) -> None:
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
        if value.trigger != DetectorTrigger.internal:
            assert (
                value.deadtime
            ), "Deadtime must be supplied when in externally triggered mode"
        if value.deadtime:
            required = self.controller.get_deadtime(value.livetime)
            assert required <= value.deadtime, (
                f"Detector {self.controller} needs at least {required}s deadtime, "
                f"but trigger logic provides only {value.deadtime}s"
            )
        self._trigger_info = value
        self._number_of_triggers_iter = iter(
            self._trigger_info.number_of_triggers
            if isinstance(self._trigger_info.number_of_triggers, list)
            else [self._trigger_info.number_of_triggers]
        )
        self._initial_frame = await self.writer.get_indices_written()
        self._describe, _ = await asyncio.gather(
            self.writer.open(value.multiplier), self.controller.prepare(value)
        )
        if value.trigger != DetectorTrigger.internal:
            await self.controller.arm()
            self._fly_start = time.monotonic()

    @AsyncStatus.wrap
    async def kickoff(self):
        if self._trigger_info is None or self._number_of_triggers_iter is None:
            raise RuntimeError("Prepare must be called before kickoff!")
        try:
            self._frames_to_complete = next(self._number_of_triggers_iter)
            self._completable_frames += self._frames_to_complete
        except StopIteration as err:
            raise RuntimeError(
                f"Kickoff called more than the configured number of "
                f"{self._trigger_info.total_number_of_triggers} iteration(s)!"
            ) from err

    @WatchableAsyncStatus.wrap
    async def complete(self):
        assert self._trigger_info
        indices_written = self.writer.observe_indices_written(
            self._trigger_info.frame_timeout
            or (
                DEFAULT_TIMEOUT
                + (self._trigger_info.livetime or 0)
                + (self._trigger_info.deadtime or 0)
            )
        )
        try:
            async for index in indices_written:
                yield WatcherUpdate(
                    name=self.name,
                    current=index,
                    initial=self._initial_frame,
                    target=self._frames_to_complete,
                    unit="",
                    precision=0,
                    time_elapsed=time.monotonic() - self._fly_start
                    if self._fly_start
                    else None,
                )
                if index >= self._frames_to_complete:
                    break
        finally:
            await indices_written.aclose()
            if self._completable_frames >= self._trigger_info.total_number_of_triggers:
                self._completable_frames = 0
                self._frames_to_complete = 0
                self._number_of_triggers_iter = None
                await self.controller.wait_for_idle()

    async def describe_collect(self) -> dict[str, DataKey]:
        return self._describe

    async def collect_asset_docs(
        self, index: int | None = None
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
