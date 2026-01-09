"""Module which defines abstract classes to work with detectors."""

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from typing import cast

from bluesky.protocols import (
    Collectable,
    EventPageCollectable,
    Flyable,
    HasHints,
    Hints,
    Preparable,
    Reading,
    Stageable,
    StreamAsset,
    Triggerable,
    WritesStreamAssets,
)
from event_model import DataKey, PartialEventPage
from pydantic import Field, NonNegativeInt, PositiveInt, computed_field

from ophyd_async.core._data_providers import StreamableDataProvider
from ophyd_async.core._settings import Settings

from ._device import Device, DeviceConnector
from ._protocol import AsyncConfigurable, AsyncReadable
from ._signal import SignalDict, SignalR, SignalRW, observe_value, soft_signal_rw
from ._status import AsyncStatus, WatchableAsyncStatus
from ._utils import (
    DEFAULT_TIMEOUT,
    ConfinedModel,
    WatcherUpdate,
    error_if_none,
    merge_gathered_dicts,
)


class DetectorTrigger(Enum):
    """Type of mechanism for triggering a detector to take exposures."""

    INTERNAL = "INTERNAL"
    """On arm generate internally timed exposures"""

    EXTERNAL_EDGE = "EXTERNAL_EDGE"
    """On every (normally rising) edge of an external input generate an internally
    timed exposure"""

    EXTERNAL_LEVEL = "EXTERNAL_LEVEL"
    """On a rising edge of an external input start an exposure, ending on the falling
    edge"""


class TriggerInfo(ConfinedModel):
    """Information required to setup `trigger` or `kickoff` on a `StandardDetector`."""

    trigger: DetectorTrigger = Field(default=DetectorTrigger.INTERNAL)
    """What sort of triggering should the detector be set for."""

    livetime: float = Field(default=0.0, ge=0.0)
    """For INTERNAL or EXTERNAL_EDGE triggering, how long should each exposure be.
    0 means whatever is currently set."""

    deadtime: float = Field(default=0.0, ge=0.0)
    """For INTERNAL triggering, how long should be left between each exposure.
    0 means use the minimum the detector supports."""

    exposures_per_collection: PositiveInt = Field(default=1)
    """An exposure corresponds to a single trigger sent to the detector.
    If many exposures are averaged together on the detector or in a processing
    chain to make a single collection that is exposed to bluesky as data then
    this number should be set to the number of exposures to be processed into a
    single collection."""

    collections_per_event: PositiveInt = Field(default=1)
    """A collection is exposed to bluesky as data, but different detectors can
    be set to have a different number of collections per event so that multiple
    collections from a faster detector can be zipped with a single collection
    from a slower detector. E.g. if number_of_events=10 and
    collections_per_event=5 then the detector will take 50 exposures, but
    publish 10 StreamDatum indices, and describe() will show a shape of (5, h,
    w) for each.
    """

    number_of_events: NonNegativeInt = Field(default=1)
    """Number of bluesky events that will be emitted, (0 means infinite)."""

    exposure_timeout: float = Field(
        default_factory=lambda d: d["livetime"] + d["deadtime"] + DEFAULT_TIMEOUT,
        gt=0,
    )
    """What is the maximum timeout on waiting for an exposure"""

    @computed_field
    @cached_property
    def number_of_collections(self) -> int:
        return self.number_of_events * self.collections_per_event

    @computed_field
    @cached_property
    def number_of_exposures(self) -> int:
        return self.number_of_collections * self.exposures_per_collection


class DetectorTriggerLogic:
    def config_sigs(self) -> set[SignalR]:
        """Return the signals that should appear in read_configuration."""
        return set()

    def get_deadtime(self, config_values: SignalDict) -> float:
        """Return the deadtime in seconds for the detector.

        :param config_values: the value of each signal in `config_sigs`
        """
        raise NotImplementedError(self)

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        """Prepare the detector to take internally triggered exposures.

        :param num: the number of exposures to take
        :param livetime: how long the exposure should be, 0 means what is currently set
        :param deadtime: how long between exposures, 0 means the shortest possible
        """
        raise NotImplementedError(self)

    async def prepare_edge(self, num: int, livetime: float):
        """Prepare the detector to take external edge triggered exposures.

        :param num: the number of exposures to take
        :param livetime: how long the exposure should be, 0 means what is currently set
        """
        raise NotImplementedError(self)

    async def prepare_level(self, num: int):
        """Prepare the detector to take external level triggered exposures.

        :param num: the number of exposures to take
        """
        raise NotImplementedError(self)

    async def prepare_exposures_per_collection(self, exposures_per_collection: int):
        """Prepare processing of multiple exposures into a single collection.

        :param exposures_per_collection:
            number of exposures to process into each collection
        """
        raise NotImplementedError(self)


def _trigger_logic_supported(method) -> bool:
    return method.__func__ is not getattr(DetectorTriggerLogic, method.__name__)


class DetectorArmLogic(ABC):
    @abstractmethod
    async def arm(self):
        """Arm the detector, waiting until it is armed."""

    @abstractmethod
    async def wait_for_idle(self):
        """Wait for the detector to be disarmed or idle."""

    @abstractmethod
    async def disarm(self):
        """Disarm the detector, return detector to an idle state."""


class ReadableDataProvider:
    @abstractmethod
    async def make_datakeys(self, collections_per_event: int) -> dict[str, DataKey]:
        """Return a DataKey for each Signal that produces a Reading.

        Called before the first exposure is taken.

        :param collections_per_event: this should appear in the shape of each DataKey
        """

    @abstractmethod
    async def make_readings(self) -> dict[str, Reading]:
        """Read the Signals and return their values."""


async def _get_collections_written(
    data_provider: ReadableDataProvider | StreamableDataProvider,
) -> int:
    if isinstance(data_provider, StreamableDataProvider):
        return await data_provider.collections_written_signal.get_value()
    else:
        return 0


class DetectorDataLogic:
    async def prepare_single(self, device_name: str) -> ReadableDataProvider:
        """Provider can only work for a single event, but can be reused."""
        raise NotImplementedError(self)

    async def prepare_multiple(
        self, device_name: str, number_of_collections: int
    ) -> StreamableDataProvider:
        """Provider can work for a known number of collections but cannot be reused."""
        raise NotImplementedError(self)

    async def prepare_unbounded(self, device_name: str) -> StreamableDataProvider:
        """Provider can work for an unbounded number of collections, can be reused."""
        raise NotImplementedError(self)

    def get_hints(self, device_name: str) -> Hints:
        """Return the hinted streams."""
        return {}

    async def stop(self) -> None: ...


def _data_logic_supported(method) -> bool:
    return method.__func__ is not getattr(DetectorDataLogic, method.__name__)


@dataclass
class _PrepareCtx:
    trigger_info: TriggerInfo
    data_provider: ReadableDataProvider | StreamableDataProvider
    can_reuse_provider: bool
    collections_written: int


@dataclass
class _KickoffCtx:
    trigger_info: TriggerInfo
    data_provider: StreamableDataProvider
    collections_written: int
    collections_requested: int
    wait_for_idle: bool


class StandardDetector(
    Device,
    Stageable,
    AsyncConfigurable,
    AsyncReadable,
    Triggerable,
    Preparable,
    Flyable,
    EventPageCollectable,
    Collectable,
    WritesStreamAssets,
    HasHints,
):
    """Detector base class for step and fly scanning detectors.

    Aggregates trigger, arm, reading or stream logic together.

    :param trigger_logic: Logic for triggering the detector
    :param data_logic: Logic for reading out or exposing the stream from the detector
    :param arm_logic: Logic for arming and disarming the detector
    :param config_sigs: Signals to read when describe and read configuration are called
    :param name: Device name
    """

    def __init__(
        self,
        trigger_logic: DetectorTriggerLogic,
        arm_logic: DetectorArmLogic,
        data_logic: DetectorDataLogic,
        config_sigs: Sequence[SignalR] = (),
        name: str = "",
        connector: DeviceConnector | None = None,
    ) -> None:
        self._trigger_logic = trigger_logic
        self._arm_logic = arm_logic
        self._data_logic = data_logic
        self._config_sigs = list(config_sigs) + list(self._trigger_logic.config_sigs())
        # Context produced by prepare, used by trigger and kickoff
        self._prepare_ctx: _PrepareCtx | None = None
        # Context produced by kickoff, used by complete
        self._kickoff_ctx: _KickoffCtx | None = None
        # Report the number of events for the next kickoff
        # TODO: only allow this to be revised down when trigger_info.number_of_events >1
        # and we have a reusable data provider
        # requries https://github.com/bluesky/ophyd-async/issues/1119
        self.events_to_kickoff = soft_signal_rw(int)
        # Store the triggers that are supported
        self._supported_triggers = set[DetectorTrigger]()
        if _trigger_logic_supported(self._trigger_logic.prepare_internal):
            self._supported_triggers.add(DetectorTrigger.INTERNAL)
        if _trigger_logic_supported(self._trigger_logic.prepare_edge):
            self._supported_triggers.add(DetectorTrigger.EXTERNAL_EDGE)
        if _trigger_logic_supported(self._trigger_logic.prepare_level):
            self._supported_triggers.add(DetectorTrigger.EXTERNAL_LEVEL)
        super().__init__(name, connector=connector)

    async def _disarm_and_stop(self):
        await asyncio.gather(self._arm_logic.disarm(), self._data_logic.stop())

    async def get_trigger_deadtime(
        self, settings: Settings | None = None
    ) -> tuple[set[DetectorTrigger], float | None]:
        """Get supported trigger types and deadtime for the detector.

        :param settings: Optional settings to use when getting configuration values
        :return: Tuple of supported trigger types and deadtime in seconds
        """
        config_values = SignalDict()
        for sig in self._trigger_logic.config_sigs():
            if settings and sig in settings:
                # Use value from settings if it is in there
                # cast to a SignalRW because settings can only contain those
                config_values[sig] = settings[cast(SignalRW, sig)]
            else:
                # Get the value live
                config_values[sig] = await sig.get_value()
        if _trigger_logic_supported(self._trigger_logic.get_deadtime):
            deadtime = self._trigger_logic.get_deadtime(config_values)
        else:
            deadtime = None
        return self._supported_triggers, deadtime

    @AsyncStatus.wrap
    async def stage(self) -> None:
        """Make sure the detector is idle and ready to be used."""
        await self._disarm_and_stop()
        self._prepare_ctx = None
        self._kickoff_ctx = None
        await self.events_to_kickoff.set(0)

    async def _update_prepare_context(self, trigger_info: TriggerInfo) -> None:
        # If we can reuse the data provider then do so
        if (
            self._prepare_ctx
            and self._prepare_ctx.can_reuse_provider
            and self._prepare_ctx.trigger_info.collections_per_event
            == trigger_info.collections_per_event
        ):
            # Reuse the existing data provider
            data_provider = self._prepare_ctx.data_provider
            can_reuse_provider = self._prepare_ctx.can_reuse_provider
        else:
            # Stop the existing provider if there was one and make a new one
            if self._prepare_ctx:
                await self._data_logic.stop()
            # Setup the data logic for the right number of collections
            if _data_logic_supported(self._data_logic.prepare_unbounded):
                data_provider = await self._data_logic.prepare_unbounded(self.name)
                can_reuse_provider = True
            elif _data_logic_supported(self._data_logic.prepare_multiple):
                data_provider = await self._data_logic.prepare_multiple(
                    self.name, trigger_info.number_of_collections
                )
                can_reuse_provider = False
            elif _data_logic_supported(self._data_logic.prepare_single):
                if trigger_info.number_of_collections > 1:
                    raise RuntimeError(f"Multiple collections not supported by {self}")
                data_provider = await self._data_logic.prepare_single(self.name)
                can_reuse_provider = True
            else:
                msg = (
                    "DataLogic hasn't overridden any prepare_* methods "
                    f"{self._data_logic}"
                )
                raise RuntimeError(msg)
        # Stash the prepare context so we can use it in trigger/kickoff
        self._prepare_ctx = _PrepareCtx(
            trigger_info=trigger_info,
            data_provider=data_provider,
            can_reuse_provider=can_reuse_provider,
            collections_written=await _get_collections_written(data_provider),
        )

    async def _wait_for_index(
        self,
        data_provider: StreamableDataProvider,
        trigger_info: TriggerInfo,
        initial_collections_written: int,
        collections_requested: int,
        done_status: AsyncStatus | None,
    ) -> AsyncIterator[WatcherUpdate]:
        start_time = time.monotonic()
        target_collections_written = initial_collections_written + collections_requested
        async for collections_written in observe_value(
            signal=data_provider.collections_written_signal,
            done_status=done_status,
            timeout=trigger_info.exposure_timeout,
        ):
            yield WatcherUpdate(
                name=self.name,
                current=collections_written // trigger_info.collections_per_event,
                initial=initial_collections_written
                // trigger_info.collections_per_event,
                target=target_collections_written // trigger_info.collections_per_event,
                unit="",
                precision=0,
                time_elapsed=time.monotonic() - start_time,
            )
            if collections_written >= target_collections_written:
                break

    @AsyncStatus.wrap
    async def prepare(self, value: TriggerInfo) -> None:
        """Prepare the detector for a number of triggers.

        :param value: TriggerInfo describing how to trigger the detector
        """
        if _trigger_logic_supported(
            self._trigger_logic.prepare_exposures_per_collection
        ):
            # If we can do multiple exposures per collection then set it up
            # even if there was only 1 requested to clear previous settings
            await self._trigger_logic.prepare_exposures_per_collection(
                value.exposures_per_collection
            )
        elif value.exposures_per_collection != 1:
            raise RuntimeError(
                f"Multiple exposures per collection not supported by {self}"
            )
        # Setup the trigger logic for the right number of exposures
        if value.trigger not in self._supported_triggers:
            raise RuntimeError(
                f"Trigger type {value.trigger} not supported by {self}, "
                f"supported types are: {self._supported_triggers}"
            )
        match value.trigger:
            case DetectorTrigger.INTERNAL:
                await self._trigger_logic.prepare_internal(
                    num=value.number_of_exposures,
                    livetime=value.livetime,
                    deadtime=value.deadtime,
                )
            case DetectorTrigger.EXTERNAL_EDGE:
                await self._trigger_logic.prepare_edge(
                    num=value.number_of_exposures,
                    livetime=value.livetime,
                )
            case DetectorTrigger.EXTERNAL_LEVEL:
                await self._trigger_logic.prepare_level(
                    num=value.number_of_exposures,
                )
            case _:
                raise ValueError(f"Unknown trigger type: {value.trigger}")
        # NOTE: this section must come after preparing the trigger logic as we may
        # use parameters from it to determine datatype for the streams
        await self._update_prepare_context(value)
        # Tell people how many collections we will acquire for
        await self.events_to_kickoff.set(value.number_of_events)
        # External triggering can arm now
        if value.trigger != DetectorTrigger.INTERNAL:
            await self._arm_logic.arm()

    @WatchableAsyncStatus.wrap
    async def trigger(self) -> AsyncIterator[WatcherUpdate[int]]:
        if self._prepare_ctx is None:
            # If a prepare has not been done since stage, do an implicit one here
            await self.prepare(TriggerInfo())
        else:
            # Check the one that was provided is suitable for triggering
            trigger_info = self._prepare_ctx.trigger_info
            if trigger_info.number_of_events != 1:
                msg = (
                    "trigger() is not supported for multiple events, the detector was "
                    f"prepared with number_of_events={trigger_info.number_of_events}."
                )
                raise ValueError(msg)
            if trigger_info.trigger is not DetectorTrigger.INTERNAL:
                msg = "The trigger method can only be called with INTERNAL triggering"
                raise ValueError(msg)
            # Ensure the data provider is still usable
            await self._update_prepare_context(trigger_info)
        ctx = error_if_none(self._prepare_ctx, "This should not happen")
        # Arm the detector and wait for it to finish.
        await self._arm_logic.arm()
        wait_for_idle_status = AsyncStatus(self._arm_logic.wait_for_idle())
        if isinstance(ctx.data_provider, StreamableDataProvider):
            async for update in self._wait_for_index(
                data_provider=ctx.data_provider,
                trigger_info=ctx.trigger_info,
                initial_collections_written=ctx.collections_written,
                collections_requested=1,
                done_status=wait_for_idle_status,
            ):
                yield update
        await wait_for_idle_status

    @AsyncStatus.wrap
    async def kickoff(self):
        ctx = error_if_none(self._prepare_ctx, "Prepare not called")
        if not isinstance(ctx.data_provider, StreamableDataProvider):
            raise ValueError(f"Detector {self} is not streamable, so cannot kickoff")
        # External trigering has been armed already, internal should arm now
        if ctx.trigger_info.trigger == DetectorTrigger.INTERNAL:
            await self._arm_logic.arm()
        collections_written = await _get_collections_written(ctx.data_provider)
        events_to_kickoff = await self.events_to_kickoff.get_value()
        collections_requested = (
            events_to_kickoff * ctx.trigger_info.collections_per_event
        )
        last_requested_collection = collections_written + collections_requested
        last_expected_collection = (
            ctx.collections_written + ctx.trigger_info.number_of_collections
        )
        if last_requested_collection > last_expected_collection:
            msg = (
                f"Kickoff requested {collections_written}:{last_requested_collection}, "
                f"but detector was only prepared up to {last_expected_collection}"
            )
            raise RuntimeError(msg)
        self._kickoff_ctx = _KickoffCtx(
            trigger_info=ctx.trigger_info,
            data_provider=ctx.data_provider,
            collections_written=collections_written,
            collections_requested=collections_requested,
            wait_for_idle=last_requested_collection == last_expected_collection,
        )

    @WatchableAsyncStatus.wrap
    async def complete(self):
        ctx = error_if_none(self._kickoff_ctx, "Kickoff not called")
        if ctx.wait_for_idle:
            wait_for_idle_status = AsyncStatus(self._arm_logic.wait_for_idle())
        else:
            wait_for_idle_status = None
        async for update in self._wait_for_index(
            data_provider=ctx.data_provider,
            trigger_info=ctx.trigger_info,
            initial_collections_written=ctx.collections_written,
            collections_requested=ctx.collections_requested,
            done_status=wait_for_idle_status,
        ):
            yield update
        if wait_for_idle_status:
            await wait_for_idle_status

    async def describe_configuration(self) -> dict[str, DataKey]:
        return await merge_gathered_dicts(sig.describe() for sig in self._config_sigs)

    async def read_configuration(self) -> dict[str, Reading]:
        return await merge_gathered_dicts(sig.read() for sig in self._config_sigs)

    async def describe(self) -> dict[str, DataKey]:
        ctx = error_if_none(self._prepare_ctx, "Prepare not run")
        return await ctx.data_provider.make_datakeys(
            ctx.trigger_info.collections_per_event
        )

    describe_collect = describe

    @property
    def hints(self) -> Hints:
        return self._data_logic.get_hints(self.name)

    async def read(self) -> dict[str, Reading]:
        ctx = error_if_none(self._prepare_ctx, "Prepare not run")
        if isinstance(ctx.data_provider, ReadableDataProvider):
            return await ctx.data_provider.make_readings()
        else:
            collections_written = await _get_collections_written(ctx.data_provider)
            async for event_page in ctx.data_provider.make_event_pages(
                collections_written=collections_written,
                collections_per_event=ctx.trigger_info.collections_per_event,
            ):
                num_events = len(event_page["data"])
                if num_events != 1:
                    msg = f"{self} produced {num_events} events in page, not 1"
                    raise RuntimeError(msg)
                readings = {
                    name: Reading(
                        value=event_page["data"][name][0],
                        timestamp=event_page["timestamps"][name][0],
                    )
                    for name in event_page["data"]
                }
                return readings
            return {}

    async def collect_pages(self) -> AsyncIterator[PartialEventPage]:
        ctx = error_if_none(self._kickoff_ctx, "Kickoff not called")
        collections_written = await _get_collections_written(ctx.data_provider)
        async for event_page in ctx.data_provider.make_event_pages(
            collections_written=collections_written,
            collections_per_event=ctx.trigger_info.collections_per_event,
        ):
            yield event_page

    async def collect_asset_docs(
        self, index: int | None = None
    ) -> AsyncIterator[StreamAsset]:
        # Collect stream datum documents for all indices written.
        # The index is optional, and provided for fly scans, however this needs to be
        # retrieved for step scans.
        ctx = error_if_none(self._prepare_ctx, "Prepare not called")
        if index is None:
            collections_written = await _get_collections_written(ctx.data_provider)
        else:
            collections_written = index * ctx.trigger_info.collections_per_event
        if isinstance(ctx.data_provider, StreamableDataProvider):
            async for doc in ctx.data_provider.make_stream_docs(
                collections_written=collections_written,
                collections_per_event=ctx.trigger_info.collections_per_event,
            ):
                yield doc

    async def get_index(self) -> int:
        ctx = error_if_none(self._prepare_ctx, "Prepare not called")
        collections_written = await _get_collections_written(ctx.data_provider)
        return collections_written // ctx.trigger_info.collections_per_event

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        """Disarm the detector and stop file writing."""
        await self._disarm_and_stop()
