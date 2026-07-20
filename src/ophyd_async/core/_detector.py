"""Module which defines abstract classes to work with detectors."""

import asyncio
import functools
import os
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
)
from event_model import DataKey
from event_model.documents import PartialEventPage
from pydantic import Field, NonNegativeInt, PositiveInt, computed_field

from ._data_providers import (
    PageableDataProvider,
    ReadableDataProvider,
    StreamableDataProvider,
)
from ._device import Device
from ._log import logger
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

    async def default_trigger_info(self) -> TriggerInfo:
        """Fallback for the default TriggerInfo in plans without prepare."""
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


class DetectorAcquireLogic(ABC):
    """Abstract base class for detector acquisition lifecycle hooks.

    Subclasses implement four hooks that are called at defined points in the
    `[](#StandardDetector)` lifecycle:

    - `ensure_ready` — called from `stage()` to put the detector into a known
      idle state before a scan begins.
    - `start_acquiring` — called from `prepare()`, `kickoff()`, or `trigger()`
      to start the detector acquiring.
    - `wait_for_idle` — called after the final collection completes to confirm
      the detector has returned to idle.
    - `ensure_stopped` — called from `unstage()` to stop the detector and
      perform any end-of-scan cleanup.

    The default `ensure_ready` delegates to `ensure_stopped`, which is correct
    for detectors where stage-time reset and scan-end teardown are identical.
    Override `ensure_ready` when the two phases require different behaviour
    (e.g. arming the detector once at stage time while keeping it armed across
    multiple kickoff/complete cycles).
    """

    async def ensure_ready(self):
        """Ensure the detector is idle before a scan.

        Called from `stage()`. The default implementation delegates to
        `ensure_stopped`, which is sufficient for detectors that perform the
        same reset at stage time as at unstage time. Override this method when
        a different action is required at stage time (for example, arming the
        detector once so it is ready for multiple kickoff/complete cycles
        without re-arming).
        """
        await self.ensure_stopped()

    @abstractmethod
    async def start_acquiring(self):
        """Start the detector acquiring.

        Called from `prepare()` for external-trigger modes, and from
        `kickoff()` / `trigger()` for internal-trigger modes.
        """

    @abstractmethod
    async def wait_for_idle(self):
        """Wait for the detector to return to idle after the final collection."""

    @abstractmethod
    async def ensure_stopped(self):
        """Stop the detector and perform end-of-scan cleanup.

        Called from `unstage()`.
        """


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
    data_providers: Sequence[StreamableDataProvider | PageableDataProvider],
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

    Implementations must override exactly one of three tiers, according to how
    many collections the data source can produce:

    - `prepare_single` for sources that only work for a single event (step scans)
    - `prepare_bounded` for sources that must be told how many collections to
      expect because they hold a finite buffer (step scans and flyscans)
    - `prepare_unbounded` for sources that work for any number of collections
      (step scans and flyscans)
    """

    #: Add this suffix to the detector name to specify the datakey. These need to be
    #: different for each DetectorDataLogic added to a detector
    datakey_suffix: str = ""

    async def prepare_single(self, datakey_name: str) -> ReadableDataProvider:
        """Provider can only work for a single event."""
        raise NotImplementedError(self)

    async def prepare_bounded(
        self, datakey_name: str, num_collections: int, period: float
    ) -> PageableDataProvider:
        """Provider works for a known, finite number of collections.

        :param num_collections: total collections the buffer must be sized for
        :param period: how long each collection takes, livetime + deadtime
        """
        raise NotImplementedError(self)

    async def prepare_unbounded(self, datakey_name: str) -> StreamableDataProvider:
        """Provider can work for an unbounded number of collections."""
        raise NotImplementedError(self)

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        """Return the hinted streams."""
        return []

    async def stop(self) -> None:
        """Stop taking data."""
        return None


_data_logic_supported = functools.partial(_logic_supported, DetectorDataLogic)


class _DataLogicTier(Enum):
    """Which prepare tier a data logic implements.

    Discovered by method-override detection (see `_data_logic_tier`); a data
    logic must override exactly one of the three `prepare_*` methods.
    """

    UNBOUNDED = "unbounded"
    BOUNDED = "bounded"
    SINGLE = "single"


def _data_logic_tier(dl: DetectorDataLogic) -> _DataLogicTier:
    """Return which prepare tier a data logic has overridden.

    Tiers are discovered by method-override detection, the same mechanism used
    for trigger logic. A data logic must override exactly one.
    """
    if _data_logic_supported(dl.prepare_unbounded):
        return _DataLogicTier.UNBOUNDED
    if _data_logic_supported(dl.prepare_bounded):
        return _DataLogicTier.BOUNDED
    if _data_logic_supported(dl.prepare_single):
        return _DataLogicTier.SINGLE
    raise RuntimeError(f"DataLogic hasn't overridden any prepare_* methods {dl}")


def _tier_can_serve(tier: _DataLogicTier, num_collections: int) -> bool:
    """Whether a tier can serve the requested number of collections.

    - unbounded serves any number, including 0 (infinite)
    - bounded serves any finite number, so not 0
    - single serves exactly 1
    """
    if tier is _DataLogicTier.UNBOUNDED:
        return True
    if tier is _DataLogicTier.BOUNDED:
        return num_collections != 0
    return num_collections == 1


@dataclass
class _PrepareCtx:
    trigger_info: TriggerInfo
    readable_data_providers: Sequence[ReadableDataProvider]
    streamable_data_providers: Sequence[StreamableDataProvider]
    pageable_data_providers: Sequence[PageableDataProvider]
    collections_written: int


@dataclass
class _KickoffCtx:
    trigger_info: TriggerInfo
    data_providers: Sequence[StreamableDataProvider | PageableDataProvider]
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
    HasHints,
):
    """Detector base class for step and fly scanning detectors.

    Aggregates trigger, arm, reading or stream logic together.

    `WritesStreamAssets` (and its `collect_asset_docs`) and
    `EventPageCollectable` (and its `collect_pages`) are *not* inherited: a
    detector writes stream assets or emits event pages depending on which data
    logics it carries, never both, and the bluesky bundler treats the two as
    mutually exclusive. The relevant method is exposed via `__getattr__` only
    when a data logic supporting it is present, so the bundler's structural
    isinstance check sees exactly the one that applies.
    """

    # Logic for the detector
    _trigger_logic: DetectorTriggerLogic | None = None
    _acquire_logic: DetectorAcquireLogic | None = None
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

    def add_detector_logics(
        self, *logics: DetectorTriggerLogic | DetectorAcquireLogic | DetectorDataLogic
    ) -> None:
        """Add acquire, trigger or data logic to the detector.

        :param logic: The logic to add
        """
        for logic in logics:
            # Each object must fill exactly one role. A single object that is both,
            # say, an AcquireLogic and a DataLogic would otherwise register as only
            # the first match and have its other role silently dropped, so require
            # separate objects even when one device's concerns live on one control.
            roles = [
                base
                for base in (
                    DetectorTriggerLogic,
                    DetectorAcquireLogic,
                    DetectorDataLogic,
                )
                if isinstance(logic, base)
            ]
            if len(roles) > 1:
                names = ", ".join(base.__name__ for base in roles)
                raise TypeError(
                    f"{type(logic).__name__} is both {names}; pass a separate object "
                    "for each logic role"
                )
            if isinstance(logic, DetectorTriggerLogic):
                if self._trigger_logic is not None:
                    raise RuntimeError("Detector already has trigger logic")
                self._trigger_logic = logic
                # Store the triggers that are supported
                self._supported_triggers = _get_supported_triggers(logic)
                # Add the config signals it needs
                self.add_config_signals(*logic.config_sigs())
            elif isinstance(logic, DetectorAcquireLogic):
                if self._acquire_logic is not None:
                    raise RuntimeError("Detector already has acquire logic")
                self._acquire_logic = logic
            elif isinstance(logic, DetectorDataLogic):
                self._data_logics = (*self._data_logics, logic)
            else:
                raise TypeError(f"Unknown logic type: {type(logic)}")
        # A detector may not mix bounded and unbounded data logics: it would expose
        # both collect_pages and collect_asset_docs and produce data from both in a
        # fly scan, which the bluesky bundler treats as mutually exclusive. A file
        # writer that also wants stats should carry them in the file (as NDAttributes)
        # rather than as a separate bounded logic.
        bounded = [
            dl for dl in self._data_logics if _data_logic_supported(dl.prepare_bounded)
        ]
        unbounded = [
            dl
            for dl in self._data_logics
            if _data_logic_supported(dl.prepare_unbounded)
        ]
        if bounded and unbounded:

            def _describe(logics: Sequence[DetectorDataLogic]) -> str:
                return ", ".join(type(dl).__name__ for dl in logics)

            raise TypeError(
                f"Detector {self.name} has both bounded data logics "
                f"({_describe(bounded)}) and unbounded data logics "
                f"({_describe(unbounded)}); these cannot be combined on one detector"
            )

    def __getattr__(self, name: str):
        # Expose collect_asset_docs / collect_pages only when a data logic that
        # produces that kind of document is present, so the bluesky bundler's
        # structural isinstance checks (WritesStreamAssets vs EventPageCollectable)
        # match exactly the one that applies. __getattr__ runs only for attributes
        # not found normally, and _data_logics has a class-level default, so this
        # never recurses.
        if name == "collect_asset_docs" and any(
            _data_logic_supported(dl.prepare_unbounded) for dl in self._data_logics
        ):
            return self._collect_asset_docs
        if name == "collect_pages" and any(
            _data_logic_supported(dl.prepare_bounded) for dl in self._data_logics
        ):
            return self._collect_pages
        # No base class defines __getattr__, so there is nothing to delegate to;
        # raise the same AttributeError the default attribute lookup would, so
        # hasattr()/getattr() and error messages behave as normal.
        raise AttributeError(
            f"{type(self).__name__!r} object has no attribute {name!r}"
        )

    def add_config_signals(self, *signals: SignalR) -> None:
        """Add a signal to read_configuration().

        :param sig: The signal to add
        """
        self._config_signals = (*self._config_signals, *signals)

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
        coros = [data_logic.stop() for data_logic in self._data_logics]
        if self._acquire_logic:
            coros.append(self._acquire_logic.ensure_ready())
        await asyncio.gather(*coros)
        self._prepare_ctx = None
        self._kickoff_ctx = None
        await self.events_to_kickoff.set(0)

    async def _resolve_period(self, value: TriggerInfo) -> TriggerInfo:
        # A livetime of 0 means "use whatever the detector currently has set". A
        # data logic that sizes chunks or a buffer by the exposure period needs a
        # real value, so read the current livetime and deadtime back from the
        # trigger logic and fill them in. This runs after the trigger logic has been
        # prepared, so the hardware already holds the values we read.
        if (
            value.livetime == 0.0
            and self._trigger_logic is not None
            and _trigger_logic_supported(self._trigger_logic.default_trigger_info)
        ):
            current = await self._trigger_logic.default_trigger_info()
            if current.livetime or current.deadtime:
                value = value.model_copy(
                    update={
                        "livetime": current.livetime,
                        "deadtime": current.deadtime,
                    }
                )
        return value

    async def _update_prepare_context(self, trigger_info: TriggerInfo) -> None:
        num_collections = trigger_info.number_of_collections
        period = trigger_info.livetime + trigger_info.deadtime
        # Classify each data logic by the tier it implements, and drop any whose
        # tier cannot serve the requested number of collections. This generalises
        # the rule from #1364 to all three tiers: rather than raising, a data logic
        # that cannot serve this scan is left out with a warning, so a detector can
        # carry, say, an unbounded file writer plus a single-only stats signal and
        # still fly with only the stats dropped.
        serving: list[tuple[DetectorDataLogic, _DataLogicTier]] = []
        for dl in self._data_logics:
            tier = _data_logic_tier(dl)
            if _tier_can_serve(tier, num_collections):
                serving.append((dl, tier))
            else:
                logger.warning(
                    "%s data logic %s cannot serve %d collections, "
                    "dropping it from this prepare",
                    tier.value,
                    self.name + dl.datakey_suffix,
                    num_collections,
                )
        # Unbounded and single providers depend on collections_per_event (it sets the
        # StreamResource shape), so may be reused across prepares when it is unchanged
        # (this avoids reopening files on every step-scan point). Bounded providers are
        # never reused: they hold a finite buffer that must be re-armed for each event,
        # and re-calling prepare_bounded on every trigger() is what re-arms it.
        # (Slice 5 will also invalidate reuse on an exposure-period change, once
        # prepare_unbounded uses the period to size its chunks.)
        reusable = (
            self._prepare_ctx is not None
            and self._prepare_ctx.trigger_info.collections_per_event
            == trigger_info.collections_per_event
        )
        if reusable and self._prepare_ctx is not None:
            readable_data_providers = self._prepare_ctx.readable_data_providers
            streamable_data_providers = self._prepare_ctx.streamable_data_providers
        else:
            # Stop the non-bounded logics we are replacing before making new ones
            if self._prepare_ctx is not None:
                await asyncio.gather(
                    *(
                        dl.stop()
                        for dl, tier in serving
                        if tier is not _DataLogicTier.BOUNDED
                    )
                )
            streamable_coros: list[Awaitable[StreamableDataProvider]] = []
            readable_coros: list[Awaitable[ReadableDataProvider]] = []
            for dl, tier in serving:
                datakey_name = self.name + dl.datakey_suffix
                if tier is _DataLogicTier.UNBOUNDED:
                    streamable_coros.append(dl.prepare_unbounded(datakey_name))
                elif tier is _DataLogicTier.SINGLE:
                    readable_coros.append(dl.prepare_single(datakey_name))
            streamable_data_providers, readable_data_providers = await asyncio.gather(
                asyncio.gather(*streamable_coros),
                asyncio.gather(*readable_coros),
            )
        # Bounded providers are always (re)built, re-arming their buffers.
        if self._prepare_ctx is not None:
            await asyncio.gather(
                *(dl.stop() for dl, tier in serving if tier is _DataLogicTier.BOUNDED)
            )
        pageable_data_providers = await asyncio.gather(
            *(
                dl.prepare_bounded(
                    self.name + dl.datakey_suffix, num_collections, period
                )
                for dl, tier in serving
                if tier is _DataLogicTier.BOUNDED
            )
        )
        # Stash the prepare context so we can use it in trigger/kickoff
        self._prepare_ctx = _PrepareCtx(
            trigger_info=trigger_info,
            streamable_data_providers=streamable_data_providers,
            readable_data_providers=readable_data_providers,
            pageable_data_providers=pageable_data_providers,
            collections_written=await _get_collections_written(
                [*streamable_data_providers, *pageable_data_providers]
            ),
        )

    async def _wait_for_index(
        self,
        data_providers: Sequence[StreamableDataProvider | PageableDataProvider],
        trigger_info: TriggerInfo,
        initial_collections_written: int,
        collections_requested: int,
        wait_for_idle: bool,
        watcher_divisor: int = 1,
    ) -> AsyncIterator[WatcherUpdate]:
        start_time = time.monotonic()
        current_collections_written = {
            dp.collections_written_signal: initial_collections_written
            for dp in data_providers
        }
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
                    current=collections_written // watcher_divisor,
                    initial=initial_collections_written // watcher_divisor,
                    target=target_collections_written // watcher_divisor,
                    unit="",
                    precision=0,
                    time_elapsed=time.monotonic() - start_time,
                )
                if collections_written >= target_collections_written:
                    break
        if self._acquire_logic and wait_for_idle:
            await self._acquire_logic.wait_for_idle()

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
        value = await self._resolve_period(value)
        await self._update_prepare_context(value)
        # Tell people how many collections we will acquire for
        await self.events_to_kickoff.set(value.number_of_events)
        # External triggering can start acquiring now
        if self._acquire_logic and value.trigger != DetectorTrigger.INTERNAL:
            await self._acquire_logic.start_acquiring()

    @WatchableAsyncStatus.wrap
    async def trigger(self) -> AsyncIterator[WatcherUpdate[int]]:
        """Trigger a single exposure.

        If [`prepare()`](#StandardDetector.prepare) has not been called since
        the last [`stage()`](#StandardDetector.stage), an implicit prepare is
        performed. When [](#OPHYD_ASYNC_PRESERVE_DETECTOR_STATE) is `YES`
        [](#DetectorTriggerLogic.default_trigger_info) is called to read current
        hardware state; otherwise a bare [`TriggerInfo()`](#TriggerInfo) is
        used.
        """
        if self._prepare_ctx is None:
            # Opt-in: set OPHYD_ASYNC_PRESERVE_DETECTOR_STATE=YES to have
            # trigger() read back current hardware state (e.g. num_images) via
            # default_trigger_info() instead of always falling back to TriggerInfo().
            # See ADR 0013 for rationale.
            # TODO: flip default to YES and remove this guard in a future PR once
            # downstream code has had time to implement default_trigger_info().
            preserve_state = (
                os.environ.get("OPHYD_ASYNC_PRESERVE_DETECTOR_STATE", "NO").upper()
                == "YES"
            )
            if preserve_state and self._trigger_logic is not None:
                if not _trigger_logic_supported(
                    self._trigger_logic.default_trigger_info
                ):
                    raise RuntimeError(
                        f"OPHYD_ASYNC_PRESERVE_DETECTOR_STATE=YES is set but "
                        f"'{self.name}' has no default_trigger_info() - implement "
                        "default_trigger_info() on your DetectorTriggerLogic subclass "
                        "or unset the environment variable."
                    )
                trigger_info = await self._trigger_logic.default_trigger_info()
            else:
                trigger_info = TriggerInfo()
            await self.prepare(trigger_info)
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
        # Start the detector acquiring and wait for it to finish.
        if self._acquire_logic:
            await self._acquire_logic.start_acquiring()
        # A bounded provider has just been re-armed by the re-prepare above, so its
        # buffer starts from zero; a streamable provider continues from wherever the
        # prepared context left it. A detector never mixes the two.
        collectable = [
            *ctx.streamable_data_providers,
            *ctx.pageable_data_providers,
        ]
        initial = 0 if ctx.pageable_data_providers else ctx.collections_written
        async for update in self._wait_for_index(
            data_providers=collectable,
            trigger_info=ctx.trigger_info,
            initial_collections_written=initial,
            collections_requested=ctx.trigger_info.collections_per_event,
            watcher_divisor=1,
            wait_for_idle=True,
        ):
            yield update

    @AsyncStatus.wrap
    async def kickoff(self):
        ctx = error_if_none(self._prepare_ctx, "Prepare not called")
        # A fly scan collects from streamable providers (as stream datums) or from
        # bounded providers (as event pages); either kind can be kicked off, but a
        # detector with neither has nothing to collect.
        collectable = [
            *ctx.streamable_data_providers,
            *ctx.pageable_data_providers,
        ]
        if not collectable:
            raise ValueError(
                f"Detector {self.name} has no collectable data, so cannot kickoff"
            )
        # Unlike trigger(), kickoff() does not re-arm a bounded buffer, so its
        # progress is read live: a fly scan arms once and accumulates across kickoffs.
        collections_written, events_to_kickoff = await asyncio.gather(
            _get_collections_written(collectable),
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
            data_providers=collectable,
            collections_written=collections_written,
            collections_requested=collections_requested,
            is_last_kickoff=last_requested_collection == last_expected_collection,
        )
        # External triggering has already started; internal starts now
        if self._acquire_logic and ctx.trigger_info.trigger == DetectorTrigger.INTERNAL:
            await self._acquire_logic.start_acquiring()

    @WatchableAsyncStatus.wrap
    async def complete(self):
        ctx = error_if_none(self._kickoff_ctx, "Kickoff not called")
        async for update in self._wait_for_index(
            data_providers=ctx.data_providers,
            trigger_info=ctx.trigger_info,
            initial_collections_written=ctx.collections_written,
            collections_requested=ctx.collections_requested,
            wait_for_idle=ctx.is_last_kickoff,
            watcher_divisor=ctx.trigger_info.collections_per_event,
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
        # Readable providers produce data during read; bounded providers produce it
        # as a single-event page that read() extracts to a reading.
        cpe = ctx.trigger_info.collections_per_event
        coros = (
            [dp.make_datakeys() for dp in ctx.readable_data_providers]
            + [dp.make_datakeys(cpe) for dp in ctx.streamable_data_providers]
            + [dp.make_datakeys(cpe) for dp in ctx.pageable_data_providers]
        )
        return await merge_gathered_dicts(coros)

    async def describe_collect(self) -> dict[str, DataKey]:
        ctx = error_if_none(self._prepare_ctx, "Prepare not run")
        # Streamable providers collect stream datums, bounded providers collect pages
        cpe = ctx.trigger_info.collections_per_event
        coros = [dp.make_datakeys(cpe) for dp in ctx.streamable_data_providers] + [
            dp.make_datakeys(cpe) for dp in ctx.pageable_data_providers
        ]
        return await merge_gathered_dicts(coros)

    @property
    def hints(self) -> Hints:
        fields: list[str] = []
        for dl in self._data_logics:
            fields.extend(dl.get_hinted_fields(self.name + dl.datakey_suffix))
        return Hints(fields=fields)

    async def read(self) -> dict[str, Reading]:
        ctx = error_if_none(self._prepare_ctx, "Prepare not called")
        cpe = ctx.trigger_info.collections_per_event
        # Readable providers read directly; bounded providers derive a reading from
        # the single-event page their buffer holds for this step-scan point.
        coros = [dp.make_readings() for dp in ctx.readable_data_providers] + [
            dp.make_readings(cpe) for dp in ctx.pageable_data_providers
        ]
        return await merge_gathered_dicts(coros)

    async def _collect_asset_docs(
        self, index: int | None = None
    ) -> AsyncIterator[StreamAsset]:
        # Collect stream datum documents for all indices written. Exposed as
        # collect_asset_docs via __getattr__ only when an unbounded data logic is
        # present, so the bluesky bundler dispatches it in place of collect_pages.
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

    async def _collect_pages(self) -> AsyncIterator[PartialEventPage]:
        # Collect event pages for all indices written. Exposed as collect_pages via
        # __getattr__ only when a bounded data logic is present, so the bluesky
        # bundler dispatches it in place of collect_asset_docs.
        ctx = error_if_none(self._prepare_ctx, "Prepare not called")
        cpe = ctx.trigger_info.collections_per_event
        index = await self.get_index()
        for data_provider in ctx.pageable_data_providers:
            async for page in data_provider.make_pages(
                collections_written=index * cpe,
                collections_per_event=cpe,
            ):
                yield page

    async def get_index(self) -> int:
        ctx = error_if_none(self._prepare_ctx, "Prepare not called")
        collectable = [
            *ctx.streamable_data_providers,
            *ctx.pageable_data_providers,
        ]
        min_collections_written = await _get_collections_written(
            collectable, reducer=min
        )
        return min_collections_written // ctx.trigger_info.collections_per_event

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        """Stop the detector and file writing."""
        coros = [data_logic.stop() for data_logic in self._data_logics]
        if self._acquire_logic:
            coros.append(self._acquire_logic.ensure_stopped())
        await asyncio.gather(*coros)
