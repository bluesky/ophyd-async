"""Module which defines abstract classes to work with detectors."""

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator, Sequence
from enum import Enum
from functools import cached_property
from typing import (
    Generic,
    TypeVar,
)

from bluesky.protocols import (
    Collectable,
    Flyable,
    Hints,
    Preparable,
    Reading,
    Stageable,
    StreamAsset,
    Triggerable,
    WritesStreamAssets,
)
from event_model import DataKey
from pydantic import BaseModel, Field, NonNegativeInt, computed_field

from ._device import Device, DeviceConnector
from ._protocol import AsyncConfigurable, AsyncReadable
from ._signal import SignalR
from ._status import AsyncStatus, WatchableAsyncStatus
from ._utils import DEFAULT_TIMEOUT, WatcherUpdate, merge_gathered_dicts


class DetectorTrigger(Enum):
    """Type of mechanism for triggering a detector to take frames."""

    INTERNAL = "INTERNAL"
    """Detector generates internal trigger for given rate"""

    EDGE_TRIGGER = "EDGE_TRIGGER"
    """Expect a series of arbitrary length trigger signals"""

    CONSTANT_GATE = "CONSTANT_GATE"
    """Expect a series of constant width external gate signals"""

    VARIABLE_GATE = "VARIABLE_GATE"
    """Expect a series of variable width external gate signals"""


class TriggerInfo(BaseModel):
    """Minimal set of information required to setup triggering on a detector."""

    number_of_triggers: NonNegativeInt | list[NonNegativeInt]
    """Number of triggers that will be sent, (0 means infinite).

    Can be:
    - A single integer or
    - A list of integers for multiple triggers

    Example for tomography: ``TriggerInfo(number=[2,3,100,3])``.
    This would trigger:

    - 2 times for dark field images
    - 3 times for initial flat field images
    - 100 times for projections
    - 3 times for final flat field images
    """

    trigger: DetectorTrigger = Field(default=DetectorTrigger.INTERNAL)
    """Sort of triggers that will be sent"""

    deadtime: float = Field(default=0.0, ge=0)
    """What is the minimum deadtime between triggers"""

    livetime: float | None = Field(default=None, ge=0)
    """What is the maximum high time of the triggers"""

    frame_timeout: float | None = Field(default=None, gt=0)
    """What is the maximum timeout on waiting for a frame"""

    multiplier: int = 1
    """How many triggers make up a single StreamDatum index, to allow multiple frames
    from a faster detector to be zipped with a single frame from a slow detector
    e.g. if num=10 and multiplier=5 then the detector will take 10 frames,
    but publish 2 indices, and describe() will show a shape of (5, h, w)
    """

    @computed_field
    @cached_property
    def total_number_of_triggers(self) -> int:
        return (
            sum(self.number_of_triggers)
            if isinstance(self.number_of_triggers, list)
            else self.number_of_triggers
        )


class DetectorController(ABC):
    """Detector logic for arming and disarming the detector."""

    @abstractmethod
    def get_deadtime(self, exposure: float | None) -> float:
        """For a given exposure, how long should the time between exposures be."""

    @abstractmethod
    async def prepare(self, trigger_info: TriggerInfo) -> None:
        """Do all necessary steps to prepare the detector for triggers.

        :param trigger_info: The sort of triggers to expect.
        """

    @abstractmethod
    async def arm(self) -> None:
        """Arm the detector."""

    @abstractmethod
    async def wait_for_idle(self):
        """Wait on the internal _arm_status and wait for it to get disarmed/idle."""

    @abstractmethod
    async def disarm(self):
        """Disarm the detector, return detector to an idle state."""

    @abstractmethod
    def is_armed(self) -> bool:
        """Return True if the detector is armed, False otherwise."""


class DetectorWriter(ABC):
    """Logic for making detector write data to somewhere persistent (e.g. HDF5 file)."""

    @abstractmethod
    async def open(self, multiplier: int = 1) -> dict[str, DataKey]:
        """Open writer and wait for it to be ready for data.

        :param multiplier:
            Each StreamDatum index corresponds to this many written exposures
        :return: Output for ``describe()``
        """

    @abstractmethod
    def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        """Yield the index of each frame (or equivalent data point) as it is written."""

    @abstractmethod
    async def get_indices_written(self) -> int:
        """Get the number of indices written."""

    @abstractmethod
    def collect_stream_docs(self, indices_written: int) -> AsyncIterator[StreamAsset]:
        """Create Stream docs up to given number written."""

    @abstractmethod
    async def close(self) -> None:
        """Close writer, blocks until I/O is complete."""

    @abstractmethod
    def is_open(self) -> bool:
        """Return True if the writer is open, False otherwise."""

    @property
    def hints(self) -> Hints:
        """The hints to be used for the detector."""
        return {}


# Add type var for controller so we can define
# StandardDetector[KinetixController, ADWriter] for example
DetectorControllerT = TypeVar("DetectorControllerT", bound=DetectorController)
DetectorWriterT = TypeVar("DetectorWriterT", bound=DetectorWriter)


def _ensure_trigger_info_exists(trigger_info: TriggerInfo | None) -> TriggerInfo:
    # make absolute sure we realy have a valid TriggerInfo ... mostly for pylance
    if trigger_info is None:
        raise RuntimeError("Trigger info must be set before calling this method.")
    return trigger_info


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
    Generic[DetectorControllerT, DetectorWriterT],
):
    """Detector base class for step and fly scanning detectors.

    Aggregates controller and writer logic together.

    :param controller: Logic for arming and disarming the detector
    :param writer: Logic for making the detector write persistent data
    :param config_sigs: Signals to read when describe and read configuration are called
    :param name: Device name
    """

    def __init__(
        self,
        controller: DetectorControllerT,
        writer: DetectorWriterT,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
        connector: DeviceConnector | None = None,
    ) -> None:
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
        super().__init__(name, connector=connector)

    @AsyncStatus.wrap
    async def stage(self) -> None:
        """Make sure the detector is idle and ready to be used."""
        await self._check_config_sigs()

        # Check to see if we need to disarm the detector or close the writer
        coros_to_await = []
        if self._writer.is_open():
            coros_to_await.append(self._writer.close)
        if self._controller.is_armed():
            coros_to_await.append(self._controller.disarm)

        await asyncio.gather(*[coro() for coro in coros_to_await])

        self._trigger_info = None

    async def _check_config_sigs(self):
        """Check configuration signals are named and connected."""
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
        """Disarm the detector and stop file writing."""
        coros_to_await = []
        if self._writer.is_open():
            coros_to_await.append(self._writer.close)
        if self._controller.is_armed():
            coros_to_await.append(self._controller.disarm)

        await asyncio.gather(*[coro() for coro in coros_to_await])

    async def read_configuration(self) -> dict[str, Reading]:
        return await merge_gathered_dicts(sig.read() for sig in self._config_sigs)

    async def describe_configuration(self) -> dict[str, DataKey]:
        return await merge_gathered_dicts(sig.describe() for sig in self._config_sigs)

    async def read(self) -> dict[str, Reading]:
        """There is no data to be placed in events, so this is empty."""
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
                    trigger=DetectorTrigger.INTERNAL,
                )
            )

        self._trigger_info = _ensure_trigger_info_exists(self._trigger_info)
        if self._trigger_info.trigger is not DetectorTrigger.INTERNAL:
            msg = "The trigger method can only be called with INTERNAL triggering"
            raise ValueError(msg)

        # Arm the detector and wait for it to finish.
        indices_written = await self._writer.get_indices_written()
        await self._controller.arm()
        await self._controller.wait_for_idle()
        end_observation = indices_written + 1

        async for index in self._writer.observe_indices_written(
            DEFAULT_TIMEOUT
            + (self._trigger_info.livetime or 0)
            + self._trigger_info.deadtime
        ):
            if index >= end_observation:
                break

    @AsyncStatus.wrap
    async def prepare(self, value: TriggerInfo) -> None:
        """Arm detector.

        Prepare the detector with trigger information. This is determined at and passed
        in from the plan level.

        :param value: TriggerInfo describing how to trigger the detector
        """
        if value.trigger != DetectorTrigger.INTERNAL and not value.deadtime:
            msg = "Deadtime must be supplied when in externally triggered mode"
            raise ValueError(msg)
        required_deadtime = self._controller.get_deadtime(value.livetime)
        if value.deadtime and required_deadtime > value.deadtime:
            msg = (
                f"Detector {self._controller} needs at least {required_deadtime}s "
                f"deadtime, but trigger logic provides only {value.deadtime}s"
            )
            raise ValueError(msg)
        elif not value.deadtime:
            value.deadtime = self._controller.get_deadtime(value.livetime)
        self._trigger_info = value
        self._number_of_triggers_iter = iter(
            self._trigger_info.number_of_triggers
            if isinstance(self._trigger_info.number_of_triggers, list)
            else [self._trigger_info.number_of_triggers]
        )
        self._describe, _ = await asyncio.gather(
            self._writer.open(value.multiplier), self._controller.prepare(value)
        )
        self._initial_frame = await self._writer.get_indices_written()
        if value.trigger != DetectorTrigger.INTERNAL:
            await self._controller.arm()
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
        self._trigger_info = _ensure_trigger_info_exists(self._trigger_info)
        indices_written = self._writer.observe_indices_written(
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
                await self._controller.wait_for_idle()

    async def describe_collect(self) -> dict[str, DataKey]:
        return self._describe

    async def collect_asset_docs(
        self, index: int | None = None
    ) -> AsyncIterator[StreamAsset]:
        # Collect stream datum documents for all indices written.
        # The index is optional, and provided for fly scans, however this needs to be
        # retrieved for step scans.
        if index is None:
            index = await self._writer.get_indices_written()
        async for doc in self._writer.collect_stream_docs(index):
            yield doc

    async def get_index(self) -> int:
        return await self._writer.get_indices_written()

    @property
    def hints(self) -> Hints:
        return self._writer.hints
