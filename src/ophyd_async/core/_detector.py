"""Module which defines abstract classes to work with detectors."""

import asyncio
import functools
import os
import time
import warnings
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from typing import cast

from bluesky.protocols import (
    Collectable,
    HasHints,
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
    StreamableDataProvider,
)
from ._flyable import StandardFlyable, WatchableFlyableLogic
from ._readable import (
    StandardReadable,
    StandardReadableFormat,
    _config_signals,
    _HintedFields,
    _Verb,
)
from ._settings import Settings
from ._signal import SignalDict, SignalR, SignalRW, observe_signals_value
from ._status import WatchableAsyncStatus
from ._utils import (
    DEFAULT_TIMEOUT,
    ConfinedModel,
    WatcherUpdate,
    abstract_cached_property,
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
    mode the detector supports, and `get_deadtime` if it supports external
    triggering.
    """

    def get_deadtime(self, config_values: SignalDict) -> float:
        """Return the deadtime in seconds for the detector.

        :param config_values:
            The value of every `Signal` the detector reports as configuration,
            i.e. everything registered with
            [](#StandardReadableFormat.CONFIG_SIGNAL), including those declared
            on children registered as [](#StandardReadableFormat.CHILD). A
            logic that needs a signal must make sure it is declared as
            configuration, rather than nominating it separately: the values
            that determine deadtime are exactly the ones that ought to be
            recorded for the scan anyway.
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


#: A provider of either kind, as returned by
#: [](#DetectorDataLogic.make_data_provider).
_DataProvider = StreamableDataProvider | PageableDataProvider


class DetectorDataLogic:
    """Abstract base class for detector data logic and handling.

    An implementation describes the data it would produce in
    `make_data_provider`, and does the writes that make it happen in `start`.
    The detector asks every data logic it has what it would make, decides which
    providers it will use, and starts only those.

    Whether the data is streamed or paged is the type of the provider that
    `make_data_provider` returns, not a declaration on the logic, so one logic
    may produce either depending on the scan.

    A source that produces a single value per event, like a plugin scalar, needs
    no data logic at all: register its signal with
    [](#StandardReadable.set_readable_format) instead.
    """

    #: Add this suffix to the detector name to specify the datakey. These need to be
    #: different for each DetectorDataLogic added to a detector
    datakey_suffix: str = ""

    async def make_data_provider(
        self, datakey_name: str, num_collections: int, period: float
    ) -> StreamableDataProvider | PageableDataProvider | None:
        """Describe the data this logic would produce for this scan.

        This must not start anything acquiring: the detector may discard the
        provider without calling `start`, and only starts the ones it will use.
        Return a [](#StreamableDataProvider) for a source that can produce any
        number of collections, or a [](#PageableDataProvider) for one holding a
        finite buffer sized to `num_collections`.

        Return `None` to sit this scan out, for instance a finite buffer asked
        for an unbounded number of collections, or a plugin that is switched
        off. This is not an error and is not warned about.

        :param datakey_name: the detector name plus this logic's datakey_suffix
        :param num_collections: total collections for the scan, 0 meaning
            unbounded
        :param period: how long each collection takes, livetime + deadtime, so
            the provider can size its chunks or its buffer. 0 means "use
            whatever is currently set on the hardware".
        """
        raise NotImplementedError(self)

    async def start(self) -> None:
        """Make the provider just returned by `make_data_provider` take data.

        Called only for the providers the detector will actually use, so this is
        where writes that arm hardware or open files belong.
        """

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        """Return the hinted streams."""
        return []

    async def stop(self) -> None:
        """Stop taking data."""
        return None


@dataclass
class _DetectorData:
    """The data providers a detector has prepared, and what they were made for.

    Outlives a single prepare -> kickoff -> complete cycle: a step scan reuses an
    open file across its points, and the RunEngine collects from a flyer after
    `complete()` has returned. Cleared by `stage()`/`unstage()`.
    """

    serving: Sequence[tuple[DetectorDataLogic, _DataProvider]]
    #: What the providers were made for, and so when they can be reused
    collections_per_event: int
    period: float

    @property
    def streamable(self) -> list[StreamableDataProvider]:
        return [dp for _, dp in self.serving if isinstance(dp, StreamableDataProvider)]

    @property
    def pageable(self) -> list[PageableDataProvider]:
        return [dp for _, dp in self.serving if isinstance(dp, PageableDataProvider)]

    @property
    def collectable(self) -> list[_DataProvider]:
        """Every provider, whether it collects as stream datums or as pages."""
        return [dp for _, dp in self.serving]


@dataclass
class _FlyCtx:
    """What prepare() set up, threaded through kickoff() to complete()."""

    trigger_info: TriggerInfo
    #: What the providers had written when kickoff() ran, None until then
    kickoff_collections_written: int | None = None


class DetectorLogic(WatchableFlyableLogic[TriggerInfo, _FlyCtx]):
    """Drive a detector through its trigger, acquire and data logics.

    :param logics:
        At most one [](#DetectorTriggerLogic), at most one
        [](#DetectorAcquireLogic), and any number of [](#DetectorDataLogic), in
        any order. Each object must fill exactly one of those roles.
    :param publish_collect_methods:
        Called from `on_prepare` with which collect verbs the data logics turn
        out to need, so that a [](#StandardDetector) can expose the matching
        bluesky protocol. A detector passes its own
        `_publish_collect_methods`; [](#StandardDetector.with_logics) does that
        for an ad-hoc one.
    """

    def __init__(
        self,
        *logics: DetectorTriggerLogic | DetectorAcquireLogic | DetectorDataLogic,
        publish_collect_methods: Callable[..., None],
    ) -> None:
        self.logics = logics
        self.publish_collect_methods = publish_collect_methods
        self.trigger_logic: DetectorTriggerLogic | None = None
        self.acquire_logic: DetectorAcquireLogic | None = None
        self.data_logics: tuple[DetectorDataLogic, ...] = ()
        #: The trigger types the trigger logic implements
        self.supported_triggers: set[DetectorTrigger] = {DetectorTrigger.INTERNAL}
        #: Prefix for the datakeys the data logics produce, set from `Device.name`
        self.datakey_prefix = ""
        #: The data providers currently prepared, or None if there are none
        self.data: _DetectorData | None = None
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
                if self.trigger_logic is not None:
                    raise RuntimeError("Detector already has trigger logic")
                self.trigger_logic = logic
                self.supported_triggers = _get_supported_triggers(logic)
            elif isinstance(logic, DetectorAcquireLogic):
                if self.acquire_logic is not None:
                    raise RuntimeError("Detector already has acquire logic")
                self.acquire_logic = logic
            elif isinstance(logic, DetectorDataLogic):
                self.data_logics = (*self.data_logics, logic)
            else:
                raise TypeError(f"Unknown logic type: {type(logic)}")
        #: Whether the trigger logic can calculate a deadtime
        self.supports_deadtime = self.trigger_logic is not None and (
            _trigger_logic_supported(self.trigger_logic.get_deadtime)
        )

    @property
    def prepared_data(self) -> _DetectorData:
        """The prepared data providers, raising if prepare() has not run."""
        return error_if_none(
            self.data, f"{self.datakey_prefix}: prepare() must be called first"
        )

    def get_deadtime(self, config_values: SignalDict) -> float:
        """Return the deadtime the trigger logic calculates from `config_values`."""
        trigger_logic = error_if_none(self.trigger_logic, "No trigger logic")
        return trigger_logic.get_deadtime(config_values)

    def get_hinted_fields(self) -> Iterator[Sequence[str]]:
        """Yield the hinted fields of each data logic that is producing data.

        Before anything is prepared every data logic is asked, since `hints` is
        read outside a scan too; once prepared, only the ones actually serving
        it, so a logic that sat the scan out does not hint at data nobody will
        produce.
        """
        logics = (
            [dl for dl, _ in self.data.serving] if self.data else list(self.data_logics)
        )
        for dl in logics:
            if fields := dl.get_hinted_fields(self._datakey_name(dl)):
                yield fields

    async def on_stage(self) -> None:
        """Stop data production and make sure the detector is idle."""
        self.data = None
        coros: list[Awaitable] = [dl.stop() for dl in self.data_logics]
        if self.acquire_logic:
            coros.append(self.acquire_logic.ensure_ready())
        await asyncio.gather(*coros)

    async def on_unstage(self) -> None:
        """Stop data production and the detector at the end of a scan."""
        self.data = None
        coros: list[Awaitable] = [dl.stop() for dl in self.data_logics]
        if self.acquire_logic:
            coros.append(self.acquire_logic.ensure_stopped())
        await asyncio.gather(*coros)

    async def on_prepare(self, value: TriggerInfo) -> _FlyCtx:
        """Set the trigger logic up and make the data providers for this scan.

        :param value: TriggerInfo describing how to trigger the detector
        """
        await self._prepare_trigger_logic(value)
        # This must come after preparing the trigger logic, as the period is read
        # back from it and may determine the datatype of the streams
        value = await self._resolve_period(value)
        await self._prepare_data(value)
        # External triggering can start acquiring now
        if self.acquire_logic and value.trigger is not DetectorTrigger.INTERNAL:
            await self.acquire_logic.start_acquiring()
        return _FlyCtx(trigger_info=value)

    async def on_kickoff(self, ctx: _FlyCtx) -> _FlyCtx:
        """Start the fly scan, noting where the providers had got to."""
        collectable = self.prepared_data.collectable
        if not collectable:
            raise ValueError(
                f"Detector {self.datakey_prefix} has no collectable data, "
                "so cannot kickoff"
            )
        ctx.kickoff_collections_written = await _get_collections_written(collectable)
        # External triggering has already started; internal starts now
        if self.acquire_logic and ctx.trigger_info.trigger is DetectorTrigger.INTERNAL:
            await self.acquire_logic.start_acquiring()
        return ctx

    def on_complete_updates(self, ctx: _FlyCtx) -> AsyncIterator[WatcherUpdate]:
        """Wait for the scan to finish, reporting collections written as progress."""
        return self._wait_for_collections(
            trigger_info=ctx.trigger_info,
            initial_collections_written=error_if_none(
                ctx.kickoff_collections_written, "Kickoff not run"
            ),
            collections_requested=ctx.trigger_info.number_of_collections,
            watcher_divisor=ctx.trigger_info.collections_per_event,
        )

    async def on_trigger(self, ctx: _FlyCtx) -> AsyncIterator[WatcherUpdate]:
        """Take one event's worth of exposures and wait for them to be written."""
        if ctx.trigger_info.number_of_events != 1:
            raise ValueError(
                "trigger() is not supported for multiple events, the detector was "
                f"prepared with number_of_events={ctx.trigger_info.number_of_events}."
            )
        # A finite buffer holds one event at a time, so it is re-armed for each
        # point of a step scan; a streaming provider carries on from where it was
        data = await self._prepare_data(ctx.trigger_info)
        # Take the baseline before acquisition starts, or frames written between
        # the two would be counted towards this event. A re-armed buffer starts
        # from zero, where a streaming provider continues from wherever it has got
        # to -- which is not where prepare left it, since a step scan triggers many
        # times against one prepare. A detector never mixes the two.
        initial = (
            0 if data.pageable else await _get_collections_written(data.collectable)
        )
        if self.acquire_logic:
            await self.acquire_logic.start_acquiring()
        async for update in self._wait_for_collections(
            trigger_info=ctx.trigger_info,
            initial_collections_written=initial,
            collections_requested=ctx.trigger_info.collections_per_event,
        ):
            yield update

    async def default_trigger_info(self) -> TriggerInfo:
        """The TriggerInfo to prepare with when a plan calls trigger() directly."""
        # Opt-in: set OPHYD_ASYNC_PRESERVE_DETECTOR_STATE=YES to have trigger() read
        # back current hardware state (e.g. num_images) via default_trigger_info()
        # instead of always falling back to TriggerInfo(). See ADR 0013.
        # TODO: flip default to YES and remove this guard in a future PR once
        # downstream code has had time to implement default_trigger_info().
        preserve_state = (
            os.environ.get("OPHYD_ASYNC_PRESERVE_DETECTOR_STATE", "NO").upper() == "YES"
        )
        if preserve_state and self.trigger_logic is not None:
            if not _trigger_logic_supported(self.trigger_logic.default_trigger_info):
                raise RuntimeError(
                    "OPHYD_ASYNC_PRESERVE_DETECTOR_STATE=YES is set but "
                    f"'{self.datakey_prefix}' has no default_trigger_info() - "
                    "implement default_trigger_info() on your DetectorTriggerLogic "
                    "subclass or unset the environment variable."
                )
            return await self.trigger_logic.default_trigger_info()
        return TriggerInfo()

    def _datakey_name(self, dl: DetectorDataLogic) -> str:
        return self.datakey_prefix + dl.datakey_suffix

    async def _prepare_trigger_logic(self, value: TriggerInfo) -> None:
        if self.trigger_logic and _trigger_logic_supported(
            self.trigger_logic.prepare_exposures_per_collection
        ):
            # If we can do multiple exposures per collection then set it up
            # even if there was only 1 requested to clear previous settings
            await self.trigger_logic.prepare_exposures_per_collection(
                value.exposures_per_collection
            )
        elif value.exposures_per_collection != 1:
            raise ValueError(
                "Multiple exposures per collection not supported by "
                f"'{self.datakey_prefix}'"
            )
        if value.trigger not in self.supported_triggers:
            format_triggers = ", ".join(sorted(t.name for t in self.supported_triggers))
            raise ValueError(
                f"Trigger type {value.trigger} not supported by "
                f"'{self.datakey_prefix}', supported types are: [{format_triggers}]"
            )
        if self.trigger_logic:
            match value.trigger:
                case DetectorTrigger.INTERNAL:
                    await self.trigger_logic.prepare_internal(
                        num=value.number_of_exposures,
                        livetime=value.livetime,
                        deadtime=value.deadtime,
                    )
                case DetectorTrigger.EXTERNAL_EDGE:
                    await self.trigger_logic.prepare_edge(
                        num=value.number_of_exposures,
                        livetime=value.livetime,
                    )
                case DetectorTrigger.EXTERNAL_LEVEL:
                    await self.trigger_logic.prepare_level(
                        num=value.number_of_exposures,
                    )
        elif value.livetime != 0.0 or value.deadtime != 0.0:
            raise ValueError(
                f"Detector {self.datakey_prefix} has no trigger logic, so cannot set "
                "livetime or deadtime"
            )

    async def _resolve_period(self, value: TriggerInfo) -> TriggerInfo:
        # A livetime of 0 means "use whatever the detector currently has set". A
        # data logic that sizes chunks or a buffer by the exposure period needs a
        # real value, so read the current livetime and deadtime back from the
        # trigger logic and fill them in. This runs after the trigger logic has been
        # prepared, so the hardware already holds the values we read.
        if (
            value.livetime == 0.0
            and self.trigger_logic is not None
            and _trigger_logic_supported(self.trigger_logic.default_trigger_info)
        ):
            current = await self.trigger_logic.default_trigger_info()
            if current.livetime or current.deadtime:
                value = value.model_copy(
                    update={
                        "livetime": current.livetime,
                        "deadtime": current.deadtime,
                    }
                )
        return value

    async def _prepare_data(self, trigger_info: TriggerInfo) -> _DetectorData:
        """Make sure the data providers are ready for this scan."""
        period = trigger_info.livetime + trigger_info.deadtime
        # Providers are reused while the scan they were made for is unchanged, so
        # that a step scan does not reopen its file on every point. Both parts of
        # the key are baked into a streaming provider when it is made: the shape
        # from collections_per_event and the chunking from the period. A finite
        # buffer is re-made either way, since re-making is what re-arms it.
        previous = self.data
        if (
            previous is not None
            and previous.collections_per_event == trigger_info.collections_per_event
            and previous.period == period
        ):
            serving = await self._rearm_bounded(previous, trigger_info)
        else:
            serving = await self._make_serving(trigger_info)
        self.data = _DetectorData(
            serving=serving,
            collections_per_event=trigger_info.collections_per_event,
            period=period,
        )
        # Which collect verb the detector exposes follows what it will actually
        # produce, so it is recomputed here rather than fixed at construction
        self.publish_collect_methods(
            stream_assets=bool(self.data.streamable),
            event_pages=bool(self.data.pageable),
        )
        return self.data

    async def _make_serving(
        self, trigger_info: TriggerInfo
    ) -> Sequence[tuple[DetectorDataLogic, _DataProvider]]:
        """Ask every data logic what it would make, and start the ones we use."""
        # Stop what is running before anything new is made, since a logic that
        # cannot describe its data without opening its file does so here
        if self.data is not None:
            await asyncio.gather(*(dl.stop() for dl, _ in self.data.serving))
        cpe = trigger_info.collections_per_event
        period = trigger_info.livetime + trigger_info.deadtime
        made = await asyncio.gather(
            *(
                dl.make_data_provider(
                    self._datakey_name(dl), trigger_info.number_of_collections, period
                )
                for dl in self.data_logics
            )
        )
        # A logic returns None to sit this scan out, e.g. a finite buffer asked
        # for an unbounded number of collections, or a plugin that is switched off
        serving = [
            (dl, dp)
            for dl, dp in zip(self.data_logics, made, strict=True)
            if dp is not None
        ]
        serving = await self._drop_shadowed(serving, cpe)
        await asyncio.gather(*(dl.start() for dl, _ in serving))
        return serving

    async def _drop_shadowed(
        self,
        serving: Sequence[tuple[DetectorDataLogic, _DataProvider]],
        collections_per_event: int,
    ) -> Sequence[tuple[DetectorDataLogic, _DataProvider]]:
        """Drop finite buffers whose datakeys the stream assets already carry.

        A detector cannot produce both stream assets and event pages: the bundler
        treats them as mutually exclusive. Carrying both logics is still useful,
        because the same quantity can be written durably into the file *and* read
        from a plugin's buffer -- an areaDetector stats total, say, which the HDF
        writer pulls in as an NDAttribute. Where every key a finite buffer would
        produce is also written to the file, the file wins and the buffer sits the
        scan out. Anything else is a conflict, so it raises.
        """
        pageable = [
            (dl, dp) for dl, dp in serving if isinstance(dp, PageableDataProvider)
        ]
        streamable = [dp for _, dp in serving if isinstance(dp, StreamableDataProvider)]
        if not (pageable and streamable):
            return serving
        stream_keys: set[str] = set()
        for dp in streamable:
            stream_keys |= set(await dp.make_datakeys(collections_per_event))
        shadowed = []
        for dl, dp in pageable:
            unshadowed = (
                set(await dp.make_datakeys(collections_per_event)) - stream_keys
            )
            if unshadowed:
                raise TypeError(
                    f"Detector {self.datakey_prefix} would produce "
                    f"{sorted(unshadowed)} as event pages and the rest of its data "
                    "as stream assets; these cannot be combined on one detector"
                )
            shadowed.append(dl)
        # Nothing has been started yet, so a shadowed logic needs no stopping
        return [(dl, dp) for dl, dp in serving if dl not in shadowed]

    async def _rearm_bounded(
        self, previous: _DetectorData, trigger_info: TriggerInfo
    ) -> Sequence[tuple[DetectorDataLogic, _DataProvider]]:
        """Re-make and re-start the finite buffers, keeping everything else."""
        period = trigger_info.livetime + trigger_info.deadtime
        serving: list[tuple[DetectorDataLogic, _DataProvider]] = []
        for dl, dp in previous.serving:
            if isinstance(dp, PageableDataProvider):
                await dl.stop()
                rearmed = await dl.make_data_provider(
                    self._datakey_name(dl), trigger_info.number_of_collections, period
                )
                if rearmed is None:
                    continue
                await dl.start()
                serving.append((dl, rearmed))
            else:
                serving.append((dl, dp))
        return serving

    async def _wait_for_collections(
        self,
        trigger_info: TriggerInfo,
        initial_collections_written: int,
        collections_requested: int,
        watcher_divisor: int = 1,
    ) -> AsyncIterator[WatcherUpdate]:
        data_providers = self.prepared_data.collectable
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
                    name=self.datakey_prefix,
                    current=collections_written // watcher_divisor,
                    initial=initial_collections_written // watcher_divisor,
                    target=target_collections_written // watcher_divisor,
                    unit="",
                    precision=0,
                    time_elapsed=time.monotonic() - start_time,
                )
                if collections_written >= target_collections_written:
                    break
        if self.acquire_logic:
            await self.acquire_logic.wait_for_idle()


class StandardDetector(
    StandardReadable,
    StandardFlyable[TriggerInfo, _FlyCtx],
    Stageable,
    Triggerable,
    Collectable,
    HasHints,
):
    """Detector base class for step and fly scanning detectors.

    Aggregates trigger, acquire and data logic together in a
    [](#DetectorLogic), which a subclass builds in its `__init__` and returns
    from `logic`:

    ```python
    class MyDetector(StandardDetector):
        def __init__(self, prefix: str, name: str = "") -> None:
            self.driver = MyDriverIO(prefix)
            self._logic = DetectorLogic(
                MyTriggerLogic(self.driver),
                MyAcquireLogic(self.driver),
                publish_collect_methods=self._publish_collect_methods,
            )
            super().__init__(name=name)

        @cached_property
        def logic(self) -> DetectorLogic:
            return self._logic
    ```

    For an ad-hoc detector, [](#StandardDetector.with_logics) does the same
    thing without a subclass.

    Signals read during a step scan are registered with
    [](#StandardReadable.set_readable_format), exactly as on any other
    `StandardReadable`; data produced by a `DetectorDataLogic` is added on top
    of those in `read()` and `describe()`.

    `read()` and `describe()` require `prepare()` to have run, and raise
    otherwise, so that a descriptor can never be emitted without the detector's
    data keys. `trigger()` prepares implicitly, so a step scan never has to do
    it explicitly. `read_configuration()` and `describe_configuration()` have no
    such requirement.

    `WritesStreamAssets` (and its `collect_asset_docs`) and
    `EventPageCollectable` (and its `collect_pages`) are *not* inherited: which
    of them applies depends on what the data logics produce for a given scan, so
    whichever it is gets bound as an instance attribute by `prepare()`.
    """

    @abstract_cached_property
    def logic(self) -> DetectorLogic:
        """The logic that drives this detector, built in the subclass `__init__`."""
        raise NotImplementedError

    @classmethod
    def with_logics(
        cls,
        *logics: DetectorTriggerLogic | DetectorAcquireLogic | DetectorDataLogic,
        name: str = "",
    ) -> "StandardDetector":
        """Make a detector from some logics, without writing a subclass.

        The logic object a `StandardDetector` needs is built with a callback into
        the Device, so it cannot be constructed before the Device it belongs to.
        This does both, for an ad-hoc detector in a plan or a test.
        """
        return _LogicsDetector(*logics, name=name)

    def set_name(self, name: str, *, child_name_separator: str | None = None) -> None:
        super().set_name(name, child_name_separator=child_name_separator)
        # The data logics name their datakeys after the Device
        self.logic.datakey_prefix = name

    def _publish_collect_methods(
        self, *, stream_assets: bool, event_pages: bool
    ) -> None:
        """Bind the collect verb that matches what the data logics will produce.

        Whichever applies is bound as a real instance attribute, so the bluesky
        bundler's isinstance checks (`WritesStreamAssets` vs
        `EventPageCollectable`) see exactly one of them. They resolve with
        `inspect.getattr_static` on Python 3.12+, which does not call
        `__getattr__`, so a dynamic hook would be invisible. Both names are
        reserved by `Device`, hence `object.__setattr__`.

        `DetectorLogic` calls this from every prepare, so the verb that no longer
        applies is removed rather than left behind from a previous scan.
        """
        for verb, method, wanted in (
            ("collect_asset_docs", self._collect_asset_docs, stream_assets),
            ("collect_pages", self._collect_pages, event_pages),
        ):
            if wanted:
                object.__setattr__(self, verb, method)
            elif verb in self.__dict__:
                object.__delattr__(self, verb)

    # Back compat - delete before 1.0
    def add_config_signals(self, *signals: SignalR) -> None:
        """Add a signal to read_configuration().

        :param sig: The signal to add
        """
        warnings.warn(
            DeprecationWarning(
                "Use `set_readable_format(signal, StandardReadableFormat"
                ".CONFIG_SIGNAL)` instead of `add_config_signals(signal)`"
            ),
            stacklevel=2,
        )
        for signal in signals:
            self.set_readable_format(signal, StandardReadableFormat.CONFIG_SIGNAL)

    async def get_trigger_deadtime(
        self, settings: Settings | None = None
    ) -> tuple[set[DetectorTrigger], float | None]:
        """Get supported trigger types and deadtime for the detector.

        The trigger logic is given the value of every signal this detector
        reports as configuration, rather than nominating the ones it wants:
        the values that determine deadtime are exactly the ones that ought to
        be recorded for the scan anyway.

        :param settings: Optional settings to use when getting configuration values
        :return: Tuple of supported trigger types and deadtime in seconds
        """
        deadtime = None
        if self.logic.supports_deadtime:
            config_values = SignalDict()
            to_read: list[SignalR] = []
            for sig in _config_signals(self):
                if settings and sig in settings:
                    # Use value from settings if it is in there
                    # cast to a SignalRW because settings can only contain those
                    config_values[sig] = settings[cast(SignalRW, sig)]
                else:
                    to_read.append(sig)
            # Read live values concurrently: this is every configuration signal
            # rather than a handful the logic named, so doing it in series would
            # be one round trip per signal
            for sig, value in zip(
                to_read,
                await asyncio.gather(*(sig.get_value() for sig in to_read)),
                strict=True,
            ):
                config_values[sig] = value
            deadtime = self.logic.get_deadtime(config_values)
        return self.logic.supported_triggers, deadtime

    @WatchableAsyncStatus.wrap
    async def trigger(self) -> AsyncIterator[WatcherUpdate[int]]:
        """Trigger a single exposure.

        If [`prepare()`](#StandardFlyable.prepare) has not been called since the
        last `stage()`, an implicit prepare is performed. When
        [](#OPHYD_ASYNC_PRESERVE_DETECTOR_STATE) is `YES`
        [](#DetectorTriggerLogic.default_trigger_info) is called to read current
        hardware state; otherwise a bare [`TriggerInfo()`](#TriggerInfo) is used.
        """
        if self.logic.data is None:
            await self.prepare(await self.logic.default_trigger_info())
        async for update in self.logic.on_trigger(self._prepared_fly_ctx):
            yield update

    def _extra_funcs_for(self, verb: _Verb) -> Iterator[Callable[[], Awaitable[dict]]]:
        """Contribute what the data logics produce to read() and describe().

        StandardReadable gathers these alongside the registered children, so
        the verb methods themselves need no overriding.

        Raises if nothing has been prepared, since an unprepared detector has no
        data keys and would otherwise emit a descriptor missing its data.
        `trigger()` prepares implicitly, so a step scan never sees this.
        `read_configuration()` and `describe_configuration()` are unaffected.
        """
        if verb not in (_Verb.DESCRIBE, _Verb.READ):
            return
        data = self.logic.prepared_data
        cpe = data.collections_per_event
        # Bounded providers hold a single-event page for this step-scan point,
        # which _pageable_readings extracts back to a reading. That extraction
        # lives here rather than on the provider so a provider cannot override it.
        for pdp in data.pageable:
            if verb is _Verb.DESCRIBE:
                yield functools.partial(pdp.make_datakeys, cpe)
            else:
                yield functools.partial(self._pageable_readings, pdp, cpe)
        if verb is _Verb.DESCRIBE:
            # Streamable providers describe their shape for a step scan, but
            # produce their data through collect_asset_docs rather than read()
            for sdp in data.streamable:
                yield functools.partial(sdp.make_datakeys, cpe)

    async def describe_collect(self) -> dict[str, DataKey]:
        data = self.logic.prepared_data
        # Streamable providers collect stream datums, bounded providers collect pages
        coros = [
            dp.make_datakeys(data.collections_per_event) for dp in data.collectable
        ]
        return await merge_gathered_dicts(coros)

    def _extra_hint_sources(self) -> Iterator[HasHints]:
        """Contribute the data logics' hinted fields alongside the children's."""
        for fields in self.logic.get_hinted_fields():
            yield _HintedFields(fields)

    async def _pageable_readings(
        self, provider: PageableDataProvider, collections_per_event: int
    ) -> dict[str, Reading]:
        """Derive readings from a bounded provider's pages for a step-scan read.

        A step-scan prepare has a single event, so the page holds one event
        whose per-key value is the `collections_per_event`-length array; this
        extracts to a single reading per key. More than one value in a page
        would mean `read()` was asked for a single reading from a multi-event
        buffer, where the answer is ambiguous, so raise rather than silently
        keep the last.
        """
        collections_written = await provider.collections_written_signal.get_value()
        readings: dict[str, Reading] = {}
        async for page in provider.make_pages(
            collections_written, collections_per_event
        ):
            times = page["time"]
            for key, values in page["data"].items():
                if len(values) != 1:
                    raise ValueError(
                        f"read() expected a single event for {key!r}, "
                        f"got a page of {len(values)}"
                    )
                readings[key] = Reading(value=values[0], timestamp=times[0])
        return readings

    async def _collect_asset_docs(
        self, index: int | None = None
    ) -> AsyncIterator[StreamAsset]:
        # Bound as collect_asset_docs when there is a streaming provider
        data = self.logic.prepared_data
        if index is None:
            # The index is optional, and provided for fly scans, if there is
            # more than one detector to make sure they collect in step
            index = await self.get_index()
        for data_provider in data.streamable:
            async for doc in data_provider.make_stream_docs(
                collections_written=index * data.collections_per_event,
                collections_per_event=data.collections_per_event,
            ):
                yield doc

    async def _collect_pages(self) -> AsyncIterator[PartialEventPage]:
        # Bound as collect_pages when there is a paging provider
        data = self.logic.prepared_data
        cpe = data.collections_per_event
        index = await self.get_index()
        for data_provider in data.pageable:
            async for page in data_provider.make_pages(
                collections_written=index * cpe,
                collections_per_event=cpe,
            ):
                yield page

    async def get_index(self) -> int:
        data = self.logic.prepared_data
        min_collections_written = await _get_collections_written(
            data.collectable, reducer=min
        )
        return min_collections_written // data.collections_per_event


class _LogicsDetector(StandardDetector):
    """A concrete `StandardDetector` built from logics, see `with_logics`."""

    def __init__(
        self,
        *logics: DetectorTriggerLogic | DetectorAcquireLogic | DetectorDataLogic,
        name: str = "",
    ) -> None:
        self._logic = DetectorLogic(
            *logics, publish_collect_methods=self._publish_collect_methods
        )
        super().__init__(name=name)

    @cached_property
    def logic(self) -> DetectorLogic:
        return self._logic
