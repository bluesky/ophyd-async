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
from pydantic import Field, NonNegativeInt, PositiveInt, computed_field

from ._device import Device, DeviceConnector
from ._protocol import AsyncConfigurable, AsyncReadable
from ._signal import SignalR
from ._status import AsyncStatus, WatchableAsyncStatus
from ._utils import DEFAULT_TIMEOUT, ConfinedModel, WatcherUpdate, merge_gathered_dicts


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


class TriggerInfo(ConfinedModel):
    """Minimal set of information required to setup triggering on a detector."""

    number_of_events: NonNegativeInt | list[NonNegativeInt] = Field(default=1)
    """Number of events that will be processed, (0 means infinite).

    Can be:
    - A single integer or
    - A list of integers for multiple events

    Example for tomography: ``TriggerInfo(number_of_events=[2,3,100,3])``.
    This would process:

    - 2 events for dark field images
    - 3 events for initial flat field images
    - 100 events for projections
    - 3 events for final flat field images
    """

    trigger: DetectorTrigger = Field(default=DetectorTrigger.INTERNAL)
    """Sort of triggers that will be sent"""

    deadtime: float = Field(default=0.0, ge=0)
    """What is the minimum deadtime between exposures"""

    livetime: float | None = Field(default=None, ge=0)
    """What is the maximum high time of the exposures"""

    exposure_timeout: float | None = Field(default=None, gt=0)
    """What is the maximum timeout on waiting for an exposure"""

    exposures_per_event: PositiveInt = 1
    """The number of exposures that are grouped into a single StreamDatum index.
    A exposures_per_event > 1 can be useful to have exposures from a faster detector
    able to be zipped with a single exposure from a slower detector. E.g. if
    number_of_events=10 and exposures_per_event=5 then the detector will take
    10 exposures, but publish 2 StreamDatum indices, and describe() will show a
    shape of (5, h, w) for each.
    Default is 1.
    """

    @computed_field
    @cached_property
    def total_number_of_exposures(self) -> int:
        return (
            sum(self.number_of_events)
            if isinstance(self.number_of_events, list)
            else self.number_of_events
        ) * self.exposures_per_event


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


class DetectorWriter(ABC):
    """Logic for making detector write data to somewhere persistent (e.g. HDF5 file)."""

    @abstractmethod
    async def open(
        self, name: str, exposures_per_event: PositiveInt = 1
    ) -> dict[str, DataKey]:
        """Open writer and wait for it to be ready for data.

        :param exposures_per_event:
            Each StreamDatum index corresponds to this many written exposures
        :return: Output for ``describe()``
        """

    def get_hints(self, name: str) -> Hints:
        """The hints to be used for the detector."""
        return {}

    @abstractmethod
    async def get_indices_written(self) -> int:
        """Get the number of indices written."""

    # Note: this method is really async, but if we make it async here then we
    # need to give it a body with a redundant yield statement, which is a bit
    # awkward. So we just leave it as a regular method and let the user
    # implement it as async.
    @abstractmethod
    def observe_indices_written(self, timeout: float) -> AsyncGenerator[int, None]:
        """Yield the index of each frame (or equivalent data point) as it is written."""

    @abstractmethod
    def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        """Create Stream docs up to given number written."""

    @abstractmethod
    async def close(self) -> None:
        """Close writer, blocks until I/O is complete."""


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
        self._events_to_complete: int = 0
        # Represents the total number of exposures that will have been completed at the
        # end of the next `complete`.
        self._completable_exposures: int = 0
        self._number_of_events_iter: Iterator[int] | None = None
        self._initial_frame: int = 0
        super().__init__(name, connector=connector)

    @AsyncStatus.wrap
    async def stage(self) -> None:
        """Make sure the detector is idle and ready to be used."""
        await self._check_config_sigs()
        await asyncio.gather(self._writer.close(), self._controller.disarm())
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
        await asyncio.gather(self._writer.close(), self._controller.disarm())

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
                    number_of_events=1,
                    trigger=DetectorTrigger.INTERNAL,
                )
            )
        trigger_info = _ensure_trigger_info_exists(self._trigger_info)
        if trigger_info.trigger is not DetectorTrigger.INTERNAL:
            msg = "The trigger method can only be called with INTERNAL triggering"
            raise ValueError(msg)
        if trigger_info.number_of_events != 1:
            raise ValueError(
                "Triggering is not supported for multiple events, the detector was "
                f"prepared with number_of_events={trigger_info.number_of_events}."
            )

        # Arm the detector and wait for it to finish.
        indices_written = await self._writer.get_indices_written()
        await self._controller.arm()
        await self._controller.wait_for_idle()
        end_observation = indices_written + 1

        async for index in self._writer.observe_indices_written(
            DEFAULT_TIMEOUT + (trigger_info.livetime or 0) + trigger_info.deadtime
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
        self._number_of_events_iter = iter(
            value.number_of_events
            if isinstance(value.number_of_events, list)
            else [value.number_of_events]
        )

        await self._controller.prepare(value)
        self._describe = await self._writer.open(self.name, value.exposures_per_event)

        self._initial_frame = await self._writer.get_indices_written()
        if value.trigger != DetectorTrigger.INTERNAL:
            await self._controller.arm()
        self._trigger_info = value

    @AsyncStatus.wrap
    async def kickoff(self):
        if self._trigger_info is None or self._number_of_events_iter is None:
            raise RuntimeError("Prepare must be called before kickoff!")
        if self._trigger_info.trigger == DetectorTrigger.INTERNAL:
            await self._controller.arm()
        self._fly_start = time.monotonic()
        try:
            self._events_to_complete = next(self._number_of_events_iter)
            self._completable_exposures += (
                self._events_to_complete * self._trigger_info.exposures_per_event
            )
        except StopIteration as err:
            raise RuntimeError(
                f"Kickoff called more than the configured number of "
                f"{self._trigger_info.total_number_of_exposures} iteration(s)!"
            ) from err

    @WatchableAsyncStatus.wrap
    async def complete(self):
        trigger_info = _ensure_trigger_info_exists(self._trigger_info)
        indices_written = self._writer.observe_indices_written(
            trigger_info.exposure_timeout
            or (
                DEFAULT_TIMEOUT
                + (trigger_info.livetime or 0)
                + (trigger_info.deadtime or 0)
            )
        )
        try:
            async for index in indices_written:
                yield WatcherUpdate(
                    name=self.name,
                    current=index,
                    initial=self._initial_frame,
                    target=self._events_to_complete,
                    unit="",
                    precision=0,
                    time_elapsed=time.monotonic() - self._fly_start
                    if self._fly_start
                    else None,
                )
                if index >= self._events_to_complete:
                    break
        finally:
            await indices_written.aclose()
            if self._completable_exposures >= trigger_info.total_number_of_exposures:
                self._completable_exposures = 0
                self._events_to_complete = 0
                self._number_of_events_iter = None
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
        async for doc in self._writer.collect_stream_docs(self.name, index):
            yield doc

    async def get_index(self) -> int:
        return await self._writer.get_indices_written()

    @property
    def hints(self) -> Hints:
        return self._writer.get_hints(self.name)
