"""Module which defines abstract classes to work with detectors."""

import asyncio
import functools
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from typing import cast

from bluesky.protocols import (
    Collectable,
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
from event_model import DataKey
from pydantic import Field, NonNegativeInt, PositiveInt, computed_field

from ._data_providers import ReadableDataProvider, StreamableDataProvider
from ._device import Device
from ._protocol import AsyncConfigurable, AsyncReadable
from ._settings import Settings
from ._signal import (
    SignalDict,
    SignalR,
    SignalRW,
    observe_signals_value,
    soft_signal_rw,
)
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
    """Logic for configuring detector triggering modes.

    This class defines the interface for detector trigger configuration, handling
    both internal and external triggering modes. Implementations should provide
    detector-specific logic for preparing the detector to operate in different
    trigger modes and manage exposure parameters.

    The class manages:
    - Configuration signals that should appear in detector metadata
    - Deadtime calculations based on detector configuration
    - Preparation for internal (self-triggered) exposures
    - Preparation for external edge-triggered exposures
    - Preparation for external level-triggered exposures
    - Multi-exposure collection batching

    Subclasses must implement the appropriate `prepare_*` method for any trigger
    mode the detector supports, `get_deadtime` if it supports external
    triggering, and `config_sigs` if the deadtime would vary according to
    detector parameters.
    """

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


def _logic_supported(base_class, method) -> bool:
    # If the function that is bound in a subclass is the same as the function
    # attached to the superclass, then the subclass has not overridden it, so
    # this method is not supported by the subclass.
    return method.__func__ is not getattr(base_class, method.__name__)


_trigger_logic_supported = functools.partial(_logic_supported, DetectorTriggerLogic)


def _get_supported_triggers(
    trigger_logic: DetectorTriggerLogic,
) -> set[DetectorTrigger]:
    supported_triggers = set()
    if _trigger_logic_supported(trigger_logic.prepare_internal):
        supported_triggers.add(DetectorTrigger.INTERNAL)
    if _trigger_logic_supported(trigger_logic.prepare_edge):
        supported_triggers.add(DetectorTrigger.EXTERNAL_EDGE)
    if _trigger_logic_supported(trigger_logic.prepare_level):
        supported_triggers.add(DetectorTrigger.EXTERNAL_LEVEL)
    return supported_triggers


class DetectorArmLogic(ABC):
    """Abstract base class for detector arming and disarming logic.

    Implementations must provide methods to arm the detector, wait for it to become
    idle, and disarm it. This interface allows for detector-specific behavior during
    the arm/disarm lifecycle.
    """

    @abstractmethod
    async def arm(self):
        """Arm the detector, waiting until it is armed."""

    @abstractmethod
    async def wait_for_idle(self):
        """Wait for the detector to be disarmed or idle."""

    @abstractmethod
    async def disarm(self):
        """Disarm the detector, return detector to an idle state."""


def _all_the_same(collections_written: set[int]) -> int:
    """Ensure all collection counts are the same, raising an error if they differ.

    :param collections_written: Set of collection counts from different providers
    :return: The single collection count value
    :raises RuntimeError: If the set contains more than one distinct value
    """
    if len(collections_written) != 1:
        msg = (
            "Detectors have written different numbers of collections: "
            + f"{collections_written}"
        )
        raise RuntimeError(msg)
    return collections_written.pop()


async def _get_collections_written(
    data_providers: Sequence[StreamableDataProvider],
    reducer: Callable[[set[int]], int] = _all_the_same,
) -> int:
    """Return a single collections_written value for the given providers.

    By default this function ensures all providers agree and returns that
    single value. If `reducer` is provided it will be called with the set of
    observed values and should return a single int to use.
    """
    # Work out where all the streamable data providers are up to
    collections_written = set(
        await asyncio.gather(
            *[sdp.collections_written_signal.get_value() for sdp in data_providers]
        )
    )
    if collections_written:
        # Let our reducer decide how to return a single int
        return reducer(collections_written)
    else:
        # There are none, this is valid as we then don't use the value anywhere
        # so just return 0
        return 0


class DetectorDataLogic:
    """Abstract base class for detector data logic and handling.

    Implementations must implement either prepare_unbounded for data sources
    that work with step scans as well as flyscans, or prepare_single for those
    that only work with step scans.
    """

    async def prepare_single(self, detector_name: str) -> ReadableDataProvider:
        """Provider can only work for a single event."""
        raise NotImplementedError(self)

    async def prepare_unbounded(self, detector_name: str) -> StreamableDataProvider:
        """Provider can work for an unbounded number of collections."""
        raise NotImplementedError(self)

    def get_hinted_fields(self, detector_name: str) -> Sequence[str]:
        """Return the hinted streams."""
        return []

    async def stop(self) -> None:
        """Stop taking data."""
        pass


_data_logic_supported = functools.partial(_logic_supported, DetectorDataLogic)


@dataclass
class _PrepareCtx:
    trigger_info: TriggerInfo
    readable_data_providers: Sequence[ReadableDataProvider]
    streamable_data_providers: Sequence[StreamableDataProvider]
    collections_written: int


@dataclass
class _KickoffCtx:
    trigger_info: TriggerInfo
    data_providers: Sequence[StreamableDataProvider]
    collections_written: int
    collections_requested: int
    is_last_kickoff: bool


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
    HasHints,
):
    """Detector base class for step and fly scanning detectors.

    Aggregates trigger, arm, reading or stream logic together.
    """

    # Logic for the detector
    _trigger_logic: DetectorTriggerLogic | None = None
    _arm_logic: DetectorArmLogic | None = None
    _data_logics: Sequence[DetectorDataLogic] = ()
    # Signals to include in read_configuration
    _config_signals: Sequence[SignalR] = ()
    # Context produced by prepare, used by trigger and kickoff
    _prepare_ctx: _PrepareCtx | None = None
    # Context produced by kickoff, used by complete
    _kickoff_ctx: _KickoffCtx | None = None
    # The triggers that are supported by the trigger logic
    _supported_triggers: set[DetectorTrigger] = {DetectorTrigger.INTERNAL}

    # Report the number of events for the next kickoff
    @cached_property
    def events_to_kickoff(self) -> SignalRW[int]:
        # TODO: only allow this to be revised down when trigger_info.number_of_events >1
        # and we have a reusable data provider
        # requries https://github.com/bluesky/ophyd-async/issues/1119
        signal = soft_signal_rw(int)
        # Name and parent this manually as `Device` doesn't know how to deal with cached
        # properties
        signal.parent = self
        signal.set_name(f"{self.name}-events_to_kickoff")
        return signal

    def add_logics(
        self, *logics: DetectorTriggerLogic | DetectorArmLogic | DetectorDataLogic
    ) -> None:
        """Add arm, trigger or data logic to the detector.

        :param logic: The logic to add
        """
        for logic in logics:
            if isinstance(logic, DetectorTriggerLogic):
                if self._trigger_logic is not None:
                    raise RuntimeError("Detector already has trigger logic")
                self._trigger_logic = logic
                # Store the triggers that are supported
                self._supported_triggers = _get_supported_triggers(logic)
                # Add the config signals it needs
                self.add_config_signals(*logic.config_sigs())
            elif isinstance(logic, DetectorArmLogic):
                if self._arm_logic is not None:
                    raise RuntimeError("Detector already has arm logic")
                self._arm_logic = logic
            elif isinstance(logic, DetectorDataLogic):
                self._data_logics = (*self._data_logics, logic)
            else:
                raise TypeError(f"Unknown logic type: {type(logic)}")

    def add_config_signals(self, *signals: SignalR) -> None:
        """Add a signal to read_configuration().

        :param sig: The signal to add
        """
        self._config_signals = (*self._config_signals, *signals)

    async def _disarm_and_stop(self):
        coros = [data_logic.stop() for data_logic in self._data_logics]
        if self._arm_logic:
            coros.append(self._arm_logic.disarm())
        await asyncio.gather(*coros)

    async def get_trigger_deadtime(
        self, settings: Settings | None = None
    ) -> tuple[set[DetectorTrigger], float | None]:
        """Get supported trigger types and deadtime for the detector.

        :param settings: Optional settings to use when getting configuration values
        :return: Tuple of supported trigger types and deadtime in seconds
        """
        if self._trigger_logic and _trigger_logic_supported(
            self._trigger_logic.get_deadtime
        ):
            config_values = SignalDict()
            for sig in self._trigger_logic.config_sigs():
                if settings and sig in settings:
                    # Use value from settings if it is in there
                    # cast to a SignalRW because settings can only contain those
                    config_values[sig] = settings[cast(SignalRW, sig)]
                else:
                    # Get the value live
                    config_values[sig] = await sig.get_value()
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
        # The only thing that would stop us being able to reuse a provider is
        # if the collections_per_event changes, as that would change the
        # StreamResource shape, so if that is the same we can reuse it.
        if (
            self._prepare_ctx
            and self._prepare_ctx.trigger_info.collections_per_event
            == trigger_info.collections_per_event
        ):
            # Reuse the existing data providers
            readable_data_providers = self._prepare_ctx.readable_data_providers
            streamable_data_providers = self._prepare_ctx.streamable_data_providers
        else:
            # Stop the existing providers if there is a context and make new ones
            if self._prepare_ctx:
                for data_logic in self._data_logics:
                    await data_logic.stop()
            # Setup the data logic for the right number of collections
            streamable_coros: list[Awaitable[StreamableDataProvider]] = []
            readable_coros: list[Awaitable[ReadableDataProvider]] = []
            for data_logic in self._data_logics:
                if _data_logic_supported(data_logic.prepare_unbounded):
                    streamable_coros.append(data_logic.prepare_unbounded(self.name))
                elif _data_logic_supported(data_logic.prepare_single):
                    if trigger_info.number_of_collections > 1:
                        raise RuntimeError(
                            f"Multiple collections not supported by {self.name}"
                        )
                    readable_coros.append(data_logic.prepare_single(self.name))
                else:
                    msg = (
                        "DataLogic hasn't overridden any prepare_* methods "
                        f"{data_logic}"
                    )
                    raise RuntimeError(msg)
            streamable_data_providers, readable_data_providers = await asyncio.gather(
                asyncio.gather(*streamable_coros),
                asyncio.gather(*readable_coros),
            )
        # Stash the prepare context so we can use it in trigger/kickoff
        self._prepare_ctx = _PrepareCtx(
            trigger_info=trigger_info,
            streamable_data_providers=streamable_data_providers,
            readable_data_providers=readable_data_providers,
            collections_written=await _get_collections_written(
                streamable_data_providers
            ),
        )

    async def _wait_for_index(
        self,
        data_providers: Sequence[StreamableDataProvider],
        trigger_info: TriggerInfo,
        initial_collections_written: int,
        collections_requested: int,
        wait_for_idle: bool,
    ) -> AsyncIterator[WatcherUpdate]:
        start_time = time.monotonic()
        current_collections_written = {
            dp.collections_written_signal: initial_collections_written
            for dp in data_providers
        }
        collections_per_event = trigger_info.collections_per_event
        target_collections_written = initial_collections_written + collections_requested
        if data_providers:
            async for sig, value in observe_signals_value(
                *current_collections_written.keys(),
                timeout=trigger_info.exposure_timeout,
            ):
                current_collections_written[sig] = value
                collections_written = min(current_collections_written.values())
                yield WatcherUpdate(
                    name=self.name,
                    current=collections_written // collections_per_event,
                    initial=initial_collections_written // collections_per_event,
                    target=target_collections_written // collections_per_event,
                    unit="",
                    precision=0,
                    time_elapsed=time.monotonic() - start_time,
                )
                if collections_written >= target_collections_written:
                    break
        if self._arm_logic and wait_for_idle:
            await self._arm_logic.wait_for_idle()

    @AsyncStatus.wrap
    async def prepare(self, value: TriggerInfo) -> None:
        """Prepare the detector for a number of triggers.

        :param value: TriggerInfo describing how to trigger the detector
        """
        if self._trigger_logic and _trigger_logic_supported(
            self._trigger_logic.prepare_exposures_per_collection
        ):
            # If we can do multiple exposures per collection then set it up
            # even if there was only 1 requested to clear previous settings
            await self._trigger_logic.prepare_exposures_per_collection(
                value.exposures_per_collection
            )
        elif value.exposures_per_collection != 1:
            raise ValueError(
                f"Multiple exposures per collection not supported by {self}"
            )
        # Setup the trigger logic for the right number of exposures
        if value.trigger not in self._supported_triggers:
            format_triggers = ", ".join(
                sorted(t.name for t in self._supported_triggers)
            )
            raise ValueError(
                f"Trigger type {value.trigger} not supported by '{self.name}', "
                f"supported types are: [{format_triggers}]"
            )
        if self._trigger_logic:
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
        elif value.livetime != 0.0 or value.deadtime != 0.0:
            raise ValueError(
                f"Detector {self.name} has no trigger logic, so cannot set livetime or "
                "deadtime"
            )
        # NOTE: this section must come after preparing the trigger logic as we may
        # use parameters from it to determine datatype for the streams
        await self._update_prepare_context(value)
        # Tell people how many collections we will acquire for
        await self.events_to_kickoff.set(value.number_of_events)
        # External triggering can arm now
        if self._arm_logic and value.trigger != DetectorTrigger.INTERNAL:
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
            # Ensure the data provider is still usable
            await self._update_prepare_context(trigger_info)
        ctx = error_if_none(self._prepare_ctx, "Prepare should have been run")
        # Arm the detector and wait for it to finish.
        if self._arm_logic:
            await self._arm_logic.arm()
        async for update in self._wait_for_index(
            data_providers=ctx.streamable_data_providers,
            trigger_info=ctx.trigger_info,
            initial_collections_written=ctx.collections_written,
            collections_requested=1,
            wait_for_idle=True,
        ):
            yield update

    @AsyncStatus.wrap
    async def kickoff(self):
        ctx = error_if_none(self._prepare_ctx, "Prepare not called")
        if not ctx.streamable_data_providers:
            raise ValueError(
                f"Detector {self.name} is not streamable, so cannot kickoff"
            )
        collections_written, events_to_kickoff = await asyncio.gather(
            _get_collections_written(ctx.streamable_data_providers),
            self.events_to_kickoff.get_value(),
        )
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
            data_providers=ctx.streamable_data_providers,
            collections_written=collections_written,
            collections_requested=collections_requested,
            is_last_kickoff=last_requested_collection == last_expected_collection,
        )
        # External trigering has been armed already, internal should arm now
        if self._arm_logic and ctx.trigger_info.trigger == DetectorTrigger.INTERNAL:
            await self._arm_logic.arm()

    @WatchableAsyncStatus.wrap
    async def complete(self):
        ctx = error_if_none(self._kickoff_ctx, "Kickoff not called")
        async for update in self._wait_for_index(
            data_providers=ctx.data_providers,
            trigger_info=ctx.trigger_info,
            initial_collections_written=ctx.collections_written,
            collections_requested=ctx.collections_requested,
            wait_for_idle=ctx.is_last_kickoff,
        ):
            yield update

    async def describe_configuration(self) -> dict[str, DataKey]:
        return await merge_gathered_dicts(
            sig.describe() for sig in self._config_signals
        )

    async def read_configuration(self) -> dict[str, Reading]:
        return await merge_gathered_dicts(sig.read() for sig in self._config_signals)

    async def describe(self) -> dict[str, DataKey]:
        ctx = error_if_none(self._prepare_ctx, "Prepare not run")
        # Readable and Streamable data providers produce data during read
        coros = [dp.make_datakeys() for dp in ctx.readable_data_providers] + [
            dp.make_datakeys(ctx.trigger_info.collections_per_event)
            for dp in ctx.streamable_data_providers
        ]
        return await merge_gathered_dicts(coros)

    async def describe_collect(self) -> dict[str, DataKey]:
        ctx = error_if_none(self._prepare_ctx, "Prepare not run")
        # Only streamable data providers produce data during collect
        coros = [
            dp.make_datakeys(ctx.trigger_info.collections_per_event)
            for dp in ctx.streamable_data_providers
        ]
        return await merge_gathered_dicts(coros)

    @property
    def hints(self) -> Hints:
        fields: list[str] = []
        for dl in self._data_logics:
            fields.extend(dl.get_hinted_fields(self.name))
        return Hints(fields=fields)

    async def read(self) -> dict[str, Reading]:
        ctx = error_if_none(self._prepare_ctx, "Prepare not called")
        return await merge_gathered_dicts(
            dp.make_readings() for dp in ctx.readable_data_providers
        )

    async def collect_asset_docs(
        self, index: int | None = None
    ) -> AsyncIterator[StreamAsset]:
        # Collect stream datum documents for all indices written.
        ctx = error_if_none(self._prepare_ctx, "Prepare not called")
        if index is None:
            # The index is optional, and provided for fly scans, if there is
            # more than one detector to make sure they collect in step
            index = await self.get_index()
        for data_provider in ctx.streamable_data_providers:
            async for doc in data_provider.make_stream_docs(
                collections_written=index * ctx.trigger_info.collections_per_event,
                collections_per_event=ctx.trigger_info.collections_per_event,
            ):
                yield doc

    async def get_index(self) -> int:
        ctx = error_if_none(self._prepare_ctx, "Prepare not called")
        min_collections_written = await _get_collections_written(
            ctx.streamable_data_providers, reducer=min
        )
        return min_collections_written // ctx.trigger_info.collections_per_event

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        """Disarm the detector and stop file writing."""
        await self._disarm_and_stop()
