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
    Flyable,
    HasHints,
    Preparable,
    Stageable,
    StreamAsset,
    Triggerable,
    WritesStreamAssets,
)
from event_model import DataKey
from pydantic import Field, NonNegativeInt, PositiveInt, computed_field

from ._data_providers import StreamableDataProvider
from ._readable import (
    StandardReadable,
    StandardReadableFormat,
    _config_signals,
    _HintedFields,
    _Verb,
)
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

    Implementations must override `prepare_unbounded`. A source that produces a
    single value per event, like a plugin scalar, does not need a data logic at
    all: register its signal with
    [](#StandardReadable.set_readable_format) instead.
    """

    #: Add this suffix to the detector name to specify the datakey. These need to be
    #: different for each DetectorDataLogic added to a detector
    datakey_suffix: str = ""

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


@dataclass
class _PrepareCtx:
    trigger_info: TriggerInfo
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
    StandardReadable,
    Stageable,
    Triggerable,
    Preparable,
    Flyable,
    Collectable,
    WritesStreamAssets,
):
    """Detector base class for step and fly scanning detectors.

    Aggregates trigger, arm, reading or stream logic together.

    Signals read during a step scan are registered with
    [](#StandardReadable.set_readable_format), exactly as on any other
    `StandardReadable`; data produced by a `DetectorDataLogic` is added on top
    of those in `read()` and `describe()`.

    `read()` and `describe()` require `prepare()` to have run, and raise
    otherwise, so that a descriptor can never be emitted without the detector's
    data keys. `trigger()` prepares implicitly, so a step scan never has to do
    it explicitly. `read_configuration()` and `describe_configuration()` have no
    such requirement.
    """

    # Logic for the detector
    _trigger_logic: DetectorTriggerLogic | None = None
    _acquire_logic: DetectorAcquireLogic | None = None
    _data_logics: Sequence[DetectorDataLogic] = ()
    # Context produced by prepare, used by trigger and kickoff
    _prepare_ctx: _PrepareCtx | None = None
    # Context produced by kickoff, used by complete
    _kickoff_ctx: _KickoffCtx | None = None
    # The triggers that are supported by the trigger logic
    _supported_triggers: set[DetectorTrigger] = {DetectorTrigger.INTERNAL}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Contribute to _StandardBase's fan out rather than replacing stage(),
        # so the readable children registered on this detector still get staged
        self._stage_funcs += (self._stage_detector,)
        self._unstage_funcs += (self._unstage_detector,)

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
            if isinstance(logic, DetectorTriggerLogic):
                if self._trigger_logic is not None:
                    raise RuntimeError("Detector already has trigger logic")
                self._trigger_logic = logic
                # Store the triggers that are supported
                self._supported_triggers = _get_supported_triggers(logic)
            elif isinstance(logic, DetectorAcquireLogic):
                if self._acquire_logic is not None:
                    raise RuntimeError("Detector already has acquire logic")
                self._acquire_logic = logic
            elif isinstance(logic, DetectorDataLogic):
                self._data_logics = (*self._data_logics, logic)
            else:
                raise TypeError(f"Unknown logic type: {type(logic)}")

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
        be recorded for the scan anyway, so a second list to keep in step
        earned nothing.

        :param settings: Optional settings to use when getting configuration values
        :return: Tuple of supported trigger types and deadtime in seconds
        """
        if self._trigger_logic and _trigger_logic_supported(
            self._trigger_logic.get_deadtime
        ):
            config_values = SignalDict()
            to_read: list[SignalR] = []
            for sig in _config_signals(self):
                if settings and sig in settings:
                    # Use value from settings if it is in there
                    # cast to a SignalRW because settings can only contain those
                    config_values[sig] = settings[cast(SignalRW, sig)]
                else:
                    to_read.append(sig)
            # Read live values concurrently: this is now every configuration
            # signal rather than a handful the logic named, so doing it in
            # series would be one round trip per signal
            for sig, value in zip(
                to_read,
                await asyncio.gather(*(sig.get_value() for sig in to_read)),
                strict=True,
            ):
                config_values[sig] = value
            deadtime = self._trigger_logic.get_deadtime(config_values)
        else:
            deadtime = None
        return self._supported_triggers, deadtime

    @AsyncStatus.wrap
    async def _stage_detector(self) -> None:
        """Make sure the detector is idle and ready to be used."""
        coros: list[Awaitable] = [data_logic.stop() for data_logic in self._data_logics]
        if self._acquire_logic:
            coros.append(self._acquire_logic.ensure_ready())
        await asyncio.gather(*coros)
        self._prepare_ctx = None
        self._kickoff_ctx = None
        await self.events_to_kickoff.set(0)

    async def _update_prepare_context(self, trigger_info: TriggerInfo) -> None:
        # The only thing that would stop us being able to reuse a provider is
        # if the collections_per_event changes, as that would change the
        # StreamResource shape. All other TriggerInfo parameters (exposures, livetime,
        # etc.) don't affect the data provider configuration.
        if (
            self._prepare_ctx
            and self._prepare_ctx.trigger_info.collections_per_event
            == trigger_info.collections_per_event
        ):
            # Reuse the existing data providers
            streamable_data_providers = self._prepare_ctx.streamable_data_providers
        else:
            # Stop the existing providers if there is a context and make new ones
            if self._prepare_ctx:
                for data_logic in self._data_logics:
                    await data_logic.stop()
            # Setup the data logic for the right number of collections
            streamable_coros: list[Awaitable[StreamableDataProvider]] = []
            for dl in self._data_logics:
                if not _data_logic_supported(dl.prepare_unbounded):
                    msg = f"DataLogic hasn't overridden any prepare_* methods {dl}"
                    raise RuntimeError(msg)
                streamable_coros.append(
                    dl.prepare_unbounded(self.name + dl.datakey_suffix)
                )
            streamable_data_providers = await asyncio.gather(*streamable_coros)

        # Stash the prepare context so we can use it in trigger/kickoff
        self._prepare_ctx = _PrepareCtx(
            trigger_info=trigger_info,
            streamable_data_providers=streamable_data_providers,
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
        the last `stage()`, an implicit prepare is
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
        async for update in self._wait_for_index(
            data_providers=ctx.streamable_data_providers,
            trigger_info=ctx.trigger_info,
            initial_collections_written=ctx.collections_written,
            collections_requested=ctx.trigger_info.collections_per_event,
            watcher_divisor=1,
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

    def _extra_funcs_for(self, verb: _Verb) -> Iterator[Callable[[], Awaitable[dict]]]:
        """Contribute what the data logics produce to read() and describe().

        StandardReadable gathers these alongside the registered children, so
        the verb methods themselves need no overriding.

        Raising when nothing has been prepared is deliberate, and predates
        registered children being readable at all: a detector that has not been
        prepared has no data keys, so a `describe()` that quietly succeeded
        would emit a descriptor missing the detector's data. In practice
        `trigger()` prepares implicitly, so `trigger_and_read` never reaches
        this. `read_configuration()` and `describe_configuration()` are
        unaffected, as this hook only feeds the data verbs.

        The cost is that the *registered children* are unreachable through
        `read()`/`describe()` until then too, since this raises before the
        registry is consulted. That is accepted rather than worked around:
        reading an unprepared detector is already defined as an error.
        """
        if verb not in (_Verb.DESCRIBE, _Verb.READ):
            return
        ctx = error_if_none(self._prepare_ctx, "Prepare not run")
        if verb is _Verb.DESCRIBE:
            # Streamable providers describe their shape for a step scan, but
            # produce their data through collect_asset_docs rather than read()
            for sdp in ctx.streamable_data_providers:
                yield functools.partial(
                    sdp.make_datakeys, ctx.trigger_info.collections_per_event
                )

    async def describe_collect(self) -> dict[str, DataKey]:
        ctx = error_if_none(self._prepare_ctx, "Prepare not run")
        # Only streamable data providers produce data during collect
        coros = [
            dp.make_datakeys(ctx.trigger_info.collections_per_event)
            for dp in ctx.streamable_data_providers
        ]
        return await merge_gathered_dicts(coros)

    def _extra_hint_sources(self) -> Iterator[HasHints]:
        """Contribute the data logics' hinted fields alongside the children's."""
        for dl in self._data_logics:
            if fields := dl.get_hinted_fields(self.name + dl.datakey_suffix):
                yield _HintedFields(fields)

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
    async def _unstage_detector(self) -> None:
        """Stop the detector and file writing."""
        coros: list[Awaitable] = [data_logic.stop() for data_logic in self._data_logics]
        if self._acquire_logic:
            coros.append(self._acquire_logic.ensure_stopped())
        await asyncio.gather(*coros)
