import asyncio
import re
from collections.abc import Sequence
from unittest.mock import ANY

import numpy as np
import pytest
from bluesky.protocols import EventPageCollectable, WritesStreamAssets
from event_model import DataKey
from event_model.documents import PartialEventPage

from ophyd_async.core import (
    Array1D,
    DetectorAcquireLogic,
    DetectorDataLogic,
    DetectorLogic,
    DetectorTrigger,
    DetectorTriggerLogic,
    PageableDataProvider,
    Settings,
    SignalDict,
    SignalR,
    StandardReadable,
    StreamableDataProvider,
    StreamResourceDataProvider,
    StreamResourceInfo,
    TriggerInfo,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.testing import (
    assert_configuration,
    assert_reading,
    wait_for_pending_wakeups,
)

# Test Logic Class Implementations


class JustInternalTriggerLogic(DetectorTriggerLogic):
    """Only supports internal triggering."""

    num: int
    livetime: float
    deadtime: float

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        self.num, self.livetime, self.deadtime = num, livetime, deadtime

    async def default_trigger_info(self) -> TriggerInfo:
        return TriggerInfo()


class AllTriggerTypesLogic(DetectorTriggerLogic):
    """Supports all types of triggering."""

    trigger: DetectorTrigger
    num: int | None = None
    livetime: float | None = None
    deadtime: float | None = None

    def get_deadtime(self, config_values: SignalDict) -> float:
        return 0.001

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        self.trigger = DetectorTrigger.INTERNAL
        self.num, self.livetime, self.deadtime = num, livetime, deadtime

    async def prepare_edge(self, num: int, livetime: float):
        self.trigger = DetectorTrigger.EXTERNAL_EDGE
        self.num, self.livetime = num, livetime

    async def prepare_level(self, num: int):
        self.trigger = DetectorTrigger.EXTERNAL_LEVEL
        self.num = num


class AveragingTriggerLogic(DetectorTriggerLogic):
    """Supports exposures per collection averaging."""

    exposures_per_collection: int
    num: int
    livetime: float
    deadtime: float

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        self.num, self.livetime, self.deadtime = num, livetime, deadtime

    async def prepare_exposures_per_collection(self, exposures_per_collection: int):
        self.exposures_per_collection = exposures_per_collection


class DeadtimeTriggerLogic(DetectorTriggerLogic):
    """Trigger logic that calculates deadtime from a signal."""

    num: int
    livetime: float
    deadtime: float

    def __init__(self, deadtime_signal: SignalR[float]):
        self.deadtime_signal = deadtime_signal

    def get_deadtime(self, config_values: SignalDict) -> float:
        """Return the deadtime from the signal value.

        The signal reaches us because the detector registers it as
        CONFIG_SIGNAL, not because this logic nominates it.
        """
        return config_values[self.deadtime_signal]

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        self.num, self.livetime, self.deadtime = num, livetime, deadtime


class MockAcquireLogic(DetectorAcquireLogic):
    """Mock acquire logic that tracks state."""

    armed = False
    arm_count = 0
    disarm_count = 0

    async def start_acquiring(self):
        self.armed = True
        self.arm_count += 1

    async def wait_for_idle(self):
        await asyncio.sleep(0.001)
        self.armed = False

    async def ensure_stopped(self):
        self.armed = False
        self.disarm_count += 1


class StreamableOnlyDataLogic(DetectorDataLogic):
    """Produces only streamable (file-based) data."""

    def __init__(self, tmp_path, datakey_suffix: str = ""):
        self.collections_written = soft_signal_rw(int)
        self.stop_count = 0
        self.tmp_path = tmp_path
        self.datakey_suffix = datakey_suffix

    async def make_data_provider(
        self, datakey_name: str, num_collections: int, period: float
    ) -> StreamableDataProvider:
        resource = StreamResourceInfo(
            data_key=datakey_name,
            shape=(10, 15),
            chunk_shape=(1, 10, 15),
            dtype_numpy="|u1",
            parameters={"dataset": "/data"},
        )
        provider = StreamResourceDataProvider(
            uri=f"file://localhost/{self.tmp_path.as_posix().lstrip('/')}/test.h5",
            resources=[resource],
            mimetype="application/x-hdf5",
            collections_written_signal=self.collections_written,
        )
        return provider

    async def stop(self) -> None:
        self.stop_count += 1

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        return [datakey_name]


class MockPageableProvider(PageableDataProvider):
    """A finite buffer emitted as event pages, one value per collection."""

    def __init__(self, datakey_name: str, collections_written_signal: SignalR[int]):
        self.datakey_name = datakey_name
        self.collections_written_signal = collections_written_signal
        self.last_emitted = 0

    async def make_datakeys(self, collections_per_event: int) -> dict[str, DataKey]:
        return {
            self.datakey_name: DataKey(
                source="mock",
                shape=[collections_per_event],
                dtype="array",
                dtype_numpy="<i8",
            )
        }

    async def make_pages(self, collections_written: int, collections_per_event: int):
        events = collections_written // collections_per_event
        if events > self.last_emitted:
            new = range(self.last_emitted, events)
            page: PartialEventPage = {
                "data": {self.datakey_name: [[0] * collections_per_event for _ in new]},
                "time": [0.0 for _ in new],
                "timestamps": {self.datakey_name: [0.0 for _ in new]},
            }
            self.last_emitted = events
            yield page


class BoundedOnlyDataLogic(DetectorDataLogic):
    """Produces bounded data held in a finite buffer, sized when it is armed."""

    def __init__(self, datakey_suffix: str = ""):
        self.datakey_suffix = datakey_suffix
        self.collections_written = soft_signal_rw(int)
        self.prepare_calls: list[tuple[int, float]] = []
        self.stop_count = 0
        self._to_start: tuple[int, float] | None = None

    async def make_data_provider(
        self, datakey_name: str, num_collections: int, period: float
    ) -> PageableDataProvider | None:
        if num_collections == 0:
            # A finite buffer cannot serve an unbounded scan
            return None
        self._to_start = (num_collections, period)
        return MockPageableProvider(datakey_name, self.collections_written)

    async def start(self) -> None:
        assert self._to_start is not None
        self.prepare_calls.append(self._to_start)
        # A real buffer clears its progress counter when armed
        await self.collections_written.set(0)

    async def stop(self) -> None:
        self.stop_count += 1

    def get_hinted_fields(self, datakey_name: str) -> Sequence[str]:
        return [datakey_name]


# Parameterized Tests for Logic Combinations


@pytest.mark.parametrize(
    "trigger_logic,expected_triggers,expected_deadtime",
    [
        (None, {DetectorTrigger.INTERNAL}, None),
        (JustInternalTriggerLogic(), {DetectorTrigger.INTERNAL}, None),
        (
            AllTriggerTypesLogic(),
            {
                DetectorTrigger.INTERNAL,
                DetectorTrigger.EXTERNAL_EDGE,
                DetectorTrigger.EXTERNAL_LEVEL,
            },
            0.001,
        ),
        (
            DeadtimeTriggerLogic(soft_signal_rw(float, 0.02)),
            {DetectorTrigger.INTERNAL},
            0.02,
        ),
    ],
)
async def test_get_trigger_deadtime(
    trigger_logic, expected_triggers, expected_deadtime
):
    """Test get_trigger_deadtime with various trigger logic implementations."""
    det = DetectorLogic(*([trigger_logic] if trigger_logic else [])).with_device()
    if isinstance(trigger_logic, DeadtimeTriggerLogic):
        # A logic that needs a signal declares it as configuration; the logic
        # no longer nominates signals separately
        det.set_readable_format(trigger_logic.deadtime_signal, Format.CONFIG_SIGNAL)
    triggers, deadtime = await det.get_trigger_deadtime()
    assert triggers == expected_triggers
    assert deadtime == expected_deadtime


async def test_get_trigger_deadtime_with_settings():
    """Test get_trigger_deadtime using values from a Settings object."""
    # Create a signal for deadtime and set its initial value
    deadtime_signal = soft_signal_rw(float, 0.02)

    # Create detector with DeadtimeTriggerLogic
    det = DetectorLogic(DeadtimeTriggerLogic(deadtime_signal)).with_device()
    det.sig = deadtime_signal
    det.set_readable_format(deadtime_signal, Format.CONFIG_SIGNAL)

    # Verify initial deadtime from signal
    triggers, deadtime = await det.get_trigger_deadtime()
    assert deadtime == 0.02

    # Create settings with a different deadtime value
    settings = Settings(det, {deadtime_signal: 0.05})

    # Verify deadtime from settings overrides signal value
    triggers, deadtime = await det.get_trigger_deadtime(settings)
    assert triggers == {DetectorTrigger.INTERNAL}
    assert deadtime == 0.05

    # Verify signal value hasn't changed
    assert await deadtime_signal.get_value() == 0.02


@pytest.mark.parametrize(
    "trigger_type",
    [
        DetectorTrigger.INTERNAL,
        DetectorTrigger.EXTERNAL_EDGE,
        DetectorTrigger.EXTERNAL_LEVEL,
    ],
)
async def test_prepare_trigger_types(trigger_type):
    """Test each trigger type is properly delegated to trigger logic."""
    trigger_logic = AllTriggerTypesLogic()
    det = DetectorLogic(trigger_logic).with_device()

    trigger_info = TriggerInfo(
        trigger=trigger_type, livetime=0.5, deadtime=0.1, number_of_events=10
    )
    await det.prepare(trigger_info)

    # Verify the right prepare method was called
    assert trigger_logic.trigger == trigger_type
    assert trigger_logic.num == 10


async def test_prepare_unsupported_trigger_type():
    """Test that preparing with unsupported trigger type raises error."""
    det = DetectorLogic(JustInternalTriggerLogic()).with_device()

    with pytest.raises(ValueError, match="Trigger type.*EXTERNAL_EDGE not supported"):
        await det.prepare(TriggerInfo(trigger=DetectorTrigger.EXTERNAL_EDGE))


@pytest.mark.parametrize(
    "exposures_per_collection,collections_per_event,number_of_events,"
    "expected_exposures,expected_number_of_collections",
    [
        (1, 1, 1, 1, 1),
        (2, 1, 1, 2, 1),
        (1, 3, 5, 15, 15),
        (2, 3, 5, 30, 15),
        (4, 2, 10, 80, 20),
    ],
)
async def test_trigger_info_calculations(
    exposures_per_collection,
    collections_per_event,
    number_of_events,
    expected_exposures,
    expected_number_of_collections,
):
    """Verify TriggerInfo correctly computes number_of_exposures."""
    info = TriggerInfo(
        exposures_per_collection=exposures_per_collection,
        collections_per_event=collections_per_event,
        number_of_events=number_of_events,
    )
    assert info.number_of_exposures == expected_exposures
    assert info.number_of_collections == expected_number_of_collections


@pytest.mark.parametrize("exposures_per_collection", [1, 2, 5, 10])
async def test_exposures_per_collection(exposures_per_collection):
    """Test exposure averaging configuration."""
    tl = AveragingTriggerLogic()
    det = DetectorLogic(tl).with_device()

    await det.prepare(
        TriggerInfo(
            exposures_per_collection=exposures_per_collection, number_of_events=5
        )
    )

    assert tl.exposures_per_collection == exposures_per_collection
    # num should be number_of_exposures (events * collections_per_event * exposures)
    assert tl.num == 5 * 1 * exposures_per_collection


async def test_exposures_per_collection_not_supported():
    """Test that exposures_per_collection > 1 fails without supporting logic."""
    det = DetectorLogic(JustInternalTriggerLogic()).with_device()

    with pytest.raises(
        ValueError, match="Multiple exposures per collection not supported"
    ):
        await det.prepare(TriggerInfo(exposures_per_collection=5))


@pytest.mark.parametrize(
    "trigger_type,arm_timing",
    [
        (DetectorTrigger.INTERNAL, "kickoff"),
        (DetectorTrigger.EXTERNAL_EDGE, "prepare"),
        (DetectorTrigger.EXTERNAL_LEVEL, "prepare"),
    ],
)
async def test_arm_timing(trigger_type, arm_timing, tmp_path):
    """Verify detector is armed at the correct time based on trigger type."""
    tl = AllTriggerTypesLogic()
    al = MockAcquireLogic()
    dl = StreamableOnlyDataLogic(tmp_path)
    det = DetectorLogic(tl, al, dl).with_device()

    # Prepare the detector
    await det.prepare(TriggerInfo(trigger=trigger_type, number_of_events=2))

    if arm_timing == "prepare":
        # External triggers should arm during prepare
        assert al.arm_count == 1
        assert al.armed is True
    else:
        # Internal triggers should not arm during prepare
        assert al.arm_count == 0
        assert al.armed is False

    # Kickoff
    await det.kickoff()

    if arm_timing == "kickoff":
        # Internal triggers should arm during kickoff
        assert al.arm_count == 1
        assert al.armed is True
    else:
        # External triggers should still be armed from prepare
        assert al.arm_count == 1
        assert al.armed is True


async def test_trigger_arms_detector(tmp_path):
    """Test that trigger() arms the detector when arm logic is present."""
    al = MockAcquireLogic()
    dl = StreamableOnlyDataLogic(tmp_path)
    det = DetectorLogic(JustInternalTriggerLogic(), al, dl).with_device()

    await det.prepare(TriggerInfo())

    # Should not be armed yet
    assert al.armed is False
    assert al.arm_count == 0

    # Trigger should arm it
    status = det.trigger()
    # Give it a moment to arm
    await wait_for_pending_wakeups(raise_if_exceeded=False)
    assert al.armed is True
    assert al.arm_count == 1

    # Complete the trigger
    await dl.collections_written.set(1)
    await status


async def test_arm_logic_called_on_stage():
    """Test that acquire logic is stopped on stage."""
    al = MockAcquireLogic()
    det = DetectorLogic(al).with_device()

    al.armed = True  # Simulate being armed
    await det.stage()

    assert al.disarm_count == 1
    assert al.armed is False


async def test_describe_before_prepare_raises(tmp_path):
    """Test that describe() fails before prepare()."""
    det = DetectorLogic(StreamableOnlyDataLogic(tmp_path)).with_device()

    with pytest.raises(RuntimeError, match="prepare.. must be called first"):
        await det.describe()


async def test_describe_collect_before_prepare_raises(tmp_path):
    """Test that describe_collect() fails before prepare()."""
    det = DetectorLogic(StreamableOnlyDataLogic(tmp_path)).with_device()

    with pytest.raises(RuntimeError, match="prepare.. must be called first"):
        await det.describe_collect()


async def test_trigger_after_multi_event_prepare_raises():
    """Test that trigger() after prepare with multiple events fails."""
    det = DetectorLogic(JustInternalTriggerLogic()).with_device()

    await det.prepare(TriggerInfo(number_of_events=5))

    with pytest.raises(ValueError, match="trigger\\(\\) is not supported for multiple"):
        await det.trigger()


async def test_preserve_detector_state_requires_default_trigger_info(
    monkeypatch: pytest.MonkeyPatch,
):
    """Test PRESERVE_DETECTOR_STATE=YES errors without default_trigger_info."""
    monkeypatch.setenv("OPHYD_ASYNC_PRESERVE_DETECTOR_STATE", "YES")
    det = DetectorLogic(AllTriggerTypesLogic()).with_device("mydet")
    # AllTriggerTypesLogic intentionally does not implement default_trigger_info
    await det.stage()

    with pytest.raises(
        RuntimeError,
        match="OPHYD_ASYNC_PRESERVE_DETECTOR_STATE=YES is set but 'mydet' has no "
        "default_trigger_info\\(\\)",
    ):
        await det.trigger()


async def test_preserve_detector_state_no_trigger_logic_falls_back(
    monkeypatch: pytest.MonkeyPatch,
):
    """When OPHYD_ASYNC_PRESERVE_DETECTOR_STATE=YES but there is no trigger logic,
    trigger() silently falls back to a bare TriggerInfo() rather than raising.
    A detector with no trigger logic has no hardware state to preserve."""
    monkeypatch.setenv("OPHYD_ASYNC_PRESERVE_DETECTOR_STATE", "YES")
    det = DetectorLogic().with_device("nodet")
    await det.stage()
    # Should not raise — no trigger logic means nothing to preserve
    await det.trigger()
    assert det.logic.data is not None
    assert det.logic.data is not None


async def test_preserve_detector_state_multi_collection_watcher_and_assets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    """When OPHYD_ASYNC_PRESERVE_DETECTOR_STATE=YES and default_trigger_info returns
    collections_per_event > 1, trigger() should wait for that many raw collections
    and collect_asset_docs() should emit one datum for the Bluesky event."""

    class MultiCollectionTriggerLogic(DetectorTriggerLogic):
        async def prepare_internal(self, num: int, livetime: float, deadtime: float):
            pass

        async def default_trigger_info(self) -> TriggerInfo:
            return TriggerInfo(collections_per_event=5)

    monkeypatch.setenv("OPHYD_ASYNC_PRESERVE_DETECTOR_STATE", "YES")
    dl = StreamableOnlyDataLogic(tmp_path)
    det = DetectorLogic(MultiCollectionTriggerLogic(), dl).with_device("multidet")
    await det.stage()

    # Collect watcher updates via watch() callback
    updates: list[dict] = []
    status = det.trigger()
    status.watch(lambda **kwargs: updates.append(kwargs))
    await wait_for_pending_wakeups(raise_if_exceeded=False)
    assert (await det.describe())["multidet"]["shape"] == [5, 10, 15]

    for collections_written in range(1, 5):
        await dl.collections_written.set(collections_written)
        await wait_for_pending_wakeups(raise_if_exceeded=False)
        assert not status.done

    await dl.collections_written.set(5)
    await status
    docs = [doc async for doc in det.collect_asset_docs()]
    assert [name for name, _ in docs] == ["stream_resource", "stream_datum"]
    assert docs[1][1]["indices"] == {"start": 0, "stop": 1}
    assert [update["current"] for update in updates] == [0, 1, 2, 3, 4, 5]
    assert all(update["target"] == 5 for update in updates)


@pytest.mark.xfail(
    reason="collect_asset_docs() checks ``dl.collections_written`` again after "
    "``trigger()``",
    strict=True,
)
async def test_collect_asset_docs_uses_trigger_observed_event(
    tmp_path,
):
    """When ``trigger()`` observes that ``dl.collections_written`` hit its target,
    ``collect_asset_docs`` should not check *again* for the same condition.

    It could be the case that ``dl.collections_written`` changes between ``trigger()``
    and ``collect_asset_docs``."""
    dl = StreamableOnlyDataLogic(tmp_path)
    dl.collections_written, set_collections_written = soft_signal_r_and_setter(
        int, getter=lambda: 0
    )
    det = DetectorLogic(JustInternalTriggerLogic(), dl).with_device("det")
    await det.prepare(TriggerInfo(collections_per_event=5, exposure_timeout=0.1))

    status = det.trigger()
    await wait_for_pending_wakeups(raise_if_exceeded=False)
    set_collections_written(5)
    await status

    docs = [doc async for doc in det.collect_asset_docs()]
    assert [name for name, _ in docs] == ["stream_resource", "stream_datum"]
    assert docs[1][1]["indices"] == {"start": 0, "stop": 1}


async def test_one_kickoff_per_prepare(tmp_path):
    """A prepare serves one kickoff/complete cycle; the next needs a new prepare."""
    dl = StreamableOnlyDataLogic(tmp_path)
    det = DetectorLogic(JustInternalTriggerLogic(), dl).with_device("foo")

    await det.prepare(TriggerInfo(number_of_events=5))
    await det.kickoff()

    # A second kickoff without an intervening complete is rejected
    with pytest.raises(RuntimeError, match="prepare.* before kickoff"):
        await det.kickoff()

    status = det.complete()
    await dl.collections_written.set(5)
    await status

    # ...and so is one after complete, until prepare() runs again
    with pytest.raises(RuntimeError, match="prepare.* before kickoff"):
        await det.kickoff()


async def test_stage_resets_state():
    """Test that stage() resets detector state."""
    det = DetectorLogic(JustInternalTriggerLogic()).with_device()

    await det.prepare(TriggerInfo(number_of_events=5))

    # Stage should reset everything
    await det.stage()

    assert det.logic.data is None
    with pytest.raises(RuntimeError, match="prepare.* must be called first"):
        await det.describe()
    with pytest.raises(RuntimeError, match="prepare.* before kickoff"):
        await det.kickoff()


async def test_hints_from_single_data_logic(tmp_path):
    """Test that hints come from data logic."""
    det = DetectorLogic(StreamableOnlyDataLogic(tmp_path)).with_device("bar")

    await det.prepare(TriggerInfo())

    assert det.hints == {"fields": ["bar"]}


async def test_hints_from_multiple_data_logics(tmp_path):
    """Test that hints are aggregated from multiple data logics."""
    dl1 = StreamableOnlyDataLogic(tmp_path)
    dl2 = StreamableOnlyDataLogic(tmp_path, datakey_suffix="-extra")
    det = DetectorLogic(dl1, dl2).with_device("bar")

    await det.prepare(TriggerInfo())

    # Should include hints from both logics
    hints = det.hints
    assert "fields" in hints
    assert hints["fields"] == ["bar", "bar-extra"]


@pytest.mark.parametrize(
    "signal_type,initial_value,expected_dtype,expected_dtype_numpy,expected_shape",
    [
        (float, 1.5, "number", "<f8", []),
        (str, "test", "string", "|S40", []),
        (Array1D[np.int32], np.array([1, 2, 3], dtype=np.int32), "array", "<i4", [3]),
    ],
)
async def test_config_signals_in_describe_configuration(
    signal_type, initial_value, expected_dtype, expected_dtype_numpy, expected_shape
):
    """Test that added config signals appear in describe_configuration."""
    det = DetectorLogic().with_device()
    signal = soft_signal_rw(
        signal_type, initial_value=initial_value, name="test-config"
    )
    det.set_readable_format(signal, Format.CONFIG_SIGNAL)

    await det.stage()

    # Check describe_configuration
    config_desc = await det.describe_configuration()
    assert config_desc == {
        "test-config": {
            "dtype": expected_dtype,
            "dtype_numpy": expected_dtype_numpy,
            "shape": expected_shape,
            "source": "soft://test-config",
        },
    }

    # Check read_configuration
    await assert_configuration(
        det,
        {
            "test-config": {"value": initial_value},
        },
    )


async def test_kickoff_without_streamable_data_raises():
    """Test that kickoff() without streamable data fails."""
    det = DetectorLogic(JustInternalTriggerLogic()).with_device("foo")

    # A detector with no data logic can still be triggered for a step scan
    await det.prepare(TriggerInfo())
    await det.trigger()  # This works

    # ...but there is nothing to collect, so it cannot be flown
    await det.prepare(TriggerInfo(number_of_events=5))
    with pytest.raises(
        ValueError, match="Detector foo has no collectable data, so cannot kickoff"
    ):
        await det.kickoff()


async def test_streamable_supports_both_step_and_fly(tmp_path):
    """Test that streamable data logic supports both step and fly scanning."""
    tl = JustInternalTriggerLogic()
    dl = StreamableOnlyDataLogic(tmp_path)
    det = DetectorLogic(tl, dl).with_device("foo")

    # Step scan should work
    status = det.trigger()
    # Yield so detector can get collections written, then set it so we complete
    await wait_for_pending_wakeups(raise_if_exceeded=False)
    await dl.collections_written.set(1)
    await wait_for_pending_wakeups(raise_if_exceeded=False)
    assert status.done
    assert status.success
    docs = [doc async for doc in det.collect_asset_docs()]
    assert docs == [
        (
            "stream_resource",
            {
                "data_key": "foo",
                "mimetype": "application/x-hdf5",
                "parameters": {
                    "chunk_shape": (1, 10, 15),
                    "dataset": "/data",
                },
                "uid": ANY,
                "uri": f"file://localhost/{tmp_path.as_posix().lstrip('/')}/test.h5",
            },
        ),
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 0, "stop": 1},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": ANY,
                "uid": ANY,
            },
        ),
    ]
    # Fly scan should also work
    await det.prepare(TriggerInfo(number_of_events=5))
    await det.kickoff()
    status = det.complete()
    # Check that setting collections written will only give the first 4
    await dl.collections_written.set(5)
    docs = [doc async for doc in det.collect_asset_docs()]
    assert docs == [
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 1, "stop": 5},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": ANY,
                "uid": ANY,
            },
        ),
    ]
    assert not status.done
    # Then one more should complete
    await dl.collections_written.set(6)
    docs = [doc async for doc in det.collect_asset_docs()]
    assert docs == [
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 5, "stop": 6},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": ANY,
                "uid": ANY,
            },
        ),
    ]
    assert status.done


async def test_read_returns_correct_values():
    """Test that read() returns the values of registered signals."""
    det = DetectorLogic().with_device("det")
    det.counts, _ = soft_signal_r_and_setter(int, 42, name="det-counts")
    det.set_readable_format(det.counts, Format.HINTED_SIGNAL)

    await det.trigger()
    await assert_reading(det, {"det-counts": {"value": 42}})


async def test_detector_with_no_logics():
    """Test that detector works with no logics for basic internal triggering."""
    det = DetectorLogic().with_device()

    # Should support only INTERNAL triggering
    triggers, deadtime = await det.get_trigger_deadtime()
    assert triggers == {DetectorTrigger.INTERNAL}
    assert deadtime is None

    # Can prepare with INTERNAL trigger but not external
    await det.prepare(TriggerInfo())

    with pytest.raises(ValueError, match="Trigger type.*not supported"):
        await det.prepare(TriggerInfo(trigger=DetectorTrigger.EXTERNAL_EDGE))


async def test_detector_without_trigger_logic_cannot_set_timing_or_exteral_triggering():
    """Test that detector without trigger logic cannot set livetime/deadtime/trigger."""
    det = DetectorLogic().with_device("foo")
    msg = "Detector foo has no trigger logic, so "

    with pytest.raises(ValueError, match=msg + "cannot set livetime or deadtime"):
        await det.prepare(TriggerInfo(livetime=0.5))

    with pytest.raises(ValueError, match=msg + "cannot set livetime or deadtime"):
        await det.prepare(TriggerInfo(deadtime=0.1))


async def test_cannot_have_two_trigger_logics():
    """Test that two trigger logics raises an error."""
    with pytest.raises(RuntimeError, match="Detector already has trigger logic"):
        DetectorLogic(JustInternalTriggerLogic(), AllTriggerTypesLogic()).with_device()


async def test_cannot_have_two_arm_logics():
    """Test that two acquire logics raises an error."""
    with pytest.raises(RuntimeError, match="Detector already has acquire logic"):
        DetectorLogic(MockAcquireLogic(), MockAcquireLogic()).with_device()


async def test_unknown_logic_type_raises():
    """Test that an unknown logic type raises TypeError."""

    class UnknownLogic:
        pass

    with pytest.raises(TypeError, match="Unknown logic type"):
        DetectorLogic(UnknownLogic()).with_device()  # type: ignore[arg-type]


async def test_logic_filling_two_roles_raises():
    """An object satisfying two logic protocols must not be silently half-registered."""

    class BothAcquireAndData(DetectorAcquireLogic, DetectorDataLogic):
        async def start_acquiring(self): ...
        async def wait_for_idle(self): ...
        async def ensure_stopped(self): ...

    with pytest.raises(
        TypeError,
        match="is both DetectorAcquireLogic, DetectorDataLogic",
    ):
        DetectorLogic(BothAcquireAndData()).with_device()


@pytest.mark.parametrize("initial_shutter_closed", [True, False])
async def test_ensure_ready_vs_ensure_stopped_hooks(initial_shutter_closed: bool):
    """ensure_ready and ensure_stopped are separate hooks.

    A detector that needs different behaviour at stage time (ensure_ready) versus
    scan-end (ensure_stopped) can override both independently.  Here a shutter
    must stay open between kickoff/complete cycles, but must close when the scan
    ends (unstage).  stage() must not close the shutter even if it was already
    closed before the scan began.
    """

    class ShutterAcquireLogic(DetectorAcquireLogic):
        def __init__(self, shutter_closed: bool):
            self.shutter_closed = shutter_closed

        async def ensure_ready(self):
            pass  # don't touch the shutter at stage time

        async def start_acquiring(self):
            self.shutter_closed = False  # open shutter when acquiring

        async def wait_for_idle(self):
            pass

        async def ensure_stopped(self):
            self.shutter_closed = True  # close shutter at end of scan

    al = ShutterAcquireLogic(initial_shutter_closed)
    det = DetectorLogic(al).with_device()

    await det.stage()
    assert (
        al.shutter_closed is initial_shutter_closed
    )  # stage() must not touch the shutter

    await det.trigger()
    assert al.shutter_closed is False  # start_acquiring() opens the shutter

    await det.unstage()
    assert al.shutter_closed is True  # unstage() must close the shutter


async def test_bounded_step_scan_reads_derived_from_page():
    """A bounded buffer describes as an array and read() derives one reading."""
    dl = BoundedOnlyDataLogic()
    det = DetectorLogic(JustInternalTriggerLogic(), dl).with_device("foo")

    ti = TriggerInfo(
        number_of_events=1, collections_per_event=5, livetime=0.1, deadtime=0.0
    )
    await det.prepare(ti)
    desc = await det.describe()
    assert desc["foo"]["shape"] == [5]
    # prepare sized the buffer for 5 collections at the 0.1s period
    assert dl.prepare_calls == [(5, pytest.approx(0.1))]

    status = det.trigger()
    await wait_for_pending_wakeups(raise_if_exceeded=False)
    await dl.collections_written.set(5)
    assert status.done
    assert status.success
    # trigger() re-armed the buffer, so prepare_bounded ran a second time
    assert dl.prepare_calls == [(5, pytest.approx(0.1)), (5, pytest.approx(0.1))]
    reading = await det.read()
    assert reading["foo"]["value"] == [0, 0, 0, 0, 0]


async def test_bounded_fly_scan_accumulates_across_kickoffs():
    """A bounded buffer is armed once at prepare and not re-armed per kickoff."""
    dl = BoundedOnlyDataLogic()
    det = DetectorLogic(JustInternalTriggerLogic(), dl).with_device("foo")

    await det.prepare(
        TriggerInfo(number_of_events=10, collections_per_event=1, livetime=0.1)
    )
    assert dl.prepare_calls == [(10, pytest.approx(0.1))]

    await det.kickoff()
    status = det.complete()
    # The buffer fills as the scan runs, and pages come out as it goes
    await dl.collections_written.set(5)
    pages = [page async for page in det._collect_pages()]
    assert pages[0]["data"]["foo"] == [[0]] * 5
    assert not status.done

    await dl.collections_written.set(10)
    pages = [page async for page in det._collect_pages()]
    assert pages[0]["data"]["foo"] == [[0]] * 5
    await status
    # kickoff() never re-arms: the buffer was only ever armed once
    assert dl.prepare_calls == [(10, pytest.approx(0.1))]


@pytest.mark.parametrize(
    "requested_livetime,default,expected_period",
    [
        # livetime unset -> resolved from the trigger logic's current state
        (0.0, TriggerInfo(livetime=0.1, deadtime=0.02), 0.12),
        # livetime given -> used as-is, no readback substitution
        (0.05, TriggerInfo(livetime=0.1, deadtime=0.02), 0.05),
        # livetime unset but trigger logic has nothing set -> stays 0
        (0.0, TriggerInfo(), 0.0),
    ],
)
async def test_prepare_resolves_zero_livetime_for_bounded_period(
    requested_livetime, default, expected_period
):
    """A livetime of 0 is filled in from the trigger logic before sizing a buffer."""

    class PeriodTriggerLogic(DetectorTriggerLogic):
        async def prepare_internal(self, num: int, livetime: float, deadtime: float):
            pass

        async def default_trigger_info(self) -> TriggerInfo:
            return default

    dl = BoundedOnlyDataLogic()
    det = DetectorLogic(PeriodTriggerLogic(), dl).with_device("foo")

    await det.prepare(
        TriggerInfo(
            number_of_events=1, collections_per_event=3, livetime=requested_livetime
        )
    )
    assert dl.prepare_calls == [(3, pytest.approx(expected_period))]


async def test_bounded_dropped_for_infinite_events():
    """A bounded buffer cannot serve an infinite scan, so it makes no provider."""
    dl = BoundedOnlyDataLogic()
    det = DetectorLogic(JustInternalTriggerLogic(), dl).with_device("foo")

    await det.prepare(TriggerInfo(number_of_events=0))

    ctx = det.logic.data
    assert ctx is not None
    assert ctx.pageable == []
    # Sitting the scan out is not an error, and nothing was armed
    assert dl.prepare_calls == []


async def test_data_logic_with_no_make_data_provider_raises():
    """Test error when a DataLogic doesn't say what it would make."""

    class EmptyDataLogic(DetectorDataLogic):
        pass

    det = DetectorLogic(EmptyDataLogic()).with_device()

    with pytest.raises(NotImplementedError):
        await det.prepare(TriggerInfo())


async def test_unstage_disarms_detector():
    """Test that unstage() calls disarm on the detector."""
    al = MockAcquireLogic()
    det = DetectorLogic(al).with_device()

    al.armed = True
    await det.unstage()

    assert al.disarm_count == 1
    assert al.armed is False


async def test_prepare_stops_data_logic_when_recreating_providers(tmp_path):
    """Test that prepare() calls stop() on data logic when recreating providers."""
    dl = StreamableOnlyDataLogic(tmp_path)
    det = DetectorLogic(JustInternalTriggerLogic(), dl).with_device("det")

    # First prepare with collections_per_event=2
    await det.prepare(TriggerInfo(number_of_events=3, collections_per_event=2))
    assert dl.stop_count == 0  # No stop on first prepare

    # Second prepare with different collections_per_event triggers recreation
    await det.prepare(TriggerInfo(number_of_events=3, collections_per_event=3))
    assert dl.stop_count == 1  # stop() should have been called


async def test_different_collections_written_raises(tmp_path):
    """Test that different collections_written values from providers raises error."""
    dl1 = StreamableOnlyDataLogic(tmp_path)
    dl2 = StreamableOnlyDataLogic(tmp_path)
    det = DetectorLogic(JustInternalTriggerLogic(), dl1, dl2).with_device("det")

    await det.prepare(TriggerInfo(number_of_events=5))

    # Set different collection counts for each data logic
    await dl1.collections_written.set(3)
    await dl2.collections_written.set(5)

    # Should raise RuntimeError when collect_asset_docs tries to validate
    with pytest.raises(
        RuntimeError,
        match=re.escape(
            "Detectors have written different numbers of collections: {3, 5}"
        ),
    ):
        await det.kickoff()


async def test_data_logic_and_registered_signal(tmp_path):
    """A registered signal and a data logic both describe(), only one collects."""
    det = DetectorLogic(
        JustInternalTriggerLogic(), StreamableOnlyDataLogic(tmp_path)
    ).with_device("det")
    det.counts, _ = soft_signal_r_and_setter(int, 42, name="det-counts")
    det.set_readable_format(det.counts, Format.HINTED_SIGNAL)

    await det.prepare(TriggerInfo())

    # Should have data from the data logic and the registered signal
    description = await det.describe()
    assert description == {
        "det": {
            "dtype": "array",
            "dtype_numpy": "|u1",
            "external": "STREAM:",
            "shape": [1, 10, 15],
            "source": f"file://localhost/{tmp_path.as_posix().lstrip('/')}/test.h5",
        },
        "det-counts": {
            "dtype": "integer",
            "dtype_numpy": "<i8",
            "shape": [],
            "source": "soft://det-counts",
        },
    }
    # But collect only has streamable
    collect_description = await det.describe_collect()
    assert collect_description == {
        "det": {
            "dtype": "array",
            "dtype_numpy": "|u1",
            "external": "STREAM:",
            "shape": [1, 10, 15],
            "source": f"file://localhost/{tmp_path.as_posix().lstrip('/')}/test.h5",
        },
    }
    # Should be able to do fly scanning (has streamable logic)
    await det.prepare(TriggerInfo(number_of_events=3))
    await det.kickoff()


async def test_collect_asset_docs_with_explicit_index(tmp_path):
    """Test collect_asset_docs() with explicitly provided index."""
    dl = StreamableOnlyDataLogic(tmp_path)
    det = DetectorLogic(JustInternalTriggerLogic(), dl).with_device("det")

    await det.prepare(TriggerInfo(number_of_events=5, collections_per_event=2))

    # Collect with explicit index (not relying on get_index)
    docs = [doc async for doc in det.collect_asset_docs(index=3)]

    # Should emit docs for 3 events
    assert docs == [
        (
            "stream_resource",
            {
                "data_key": "det",
                "mimetype": "application/x-hdf5",
                "parameters": {
                    "chunk_shape": (1, 10, 15),
                    "dataset": "/data",
                },
                "uid": ANY,
                "uri": f"file://localhost/{tmp_path.as_posix().lstrip('/')}/test.h5",
            },
        ),
        (
            "stream_datum",
            {
                "descriptor": "",
                "indices": {"start": 0, "stop": 3},
                "seq_nums": {"start": 0, "stop": 0},
                "stream_resource": ANY,
                "uid": ANY,
            },
        ),
    ]


async def test_child_readable_config_signals_in_describe_configuration():
    """Child StandardReadable CONFIG_SIGNALs appear in describe_configuration."""
    child = StandardReadable(name="child")
    config_sig = soft_signal_rw(float, initial_value=1.5, name="child-exposure")
    child.add_readables([config_sig], Format.CONFIG_SIGNAL)

    det = DetectorLogic().with_device("det")
    det.add_readables([child], Format.CHILD)
    await det.prepare(TriggerInfo())

    config = await det.describe_configuration()
    assert "child-exposure" in config
    reading = await det.read_configuration()
    assert "child-exposure" in reading
    assert reading["child-exposure"]["value"] == 1.5


async def test_child_readable_read_signals_in_read(tmp_path):
    """Child StandardReadable HINTED_SIGNALs appear in read/describe."""
    child = StandardReadable(name="child")
    read_sig = soft_signal_rw(int, initial_value=99, name="child-counts")
    child.add_readables([read_sig], Format.HINTED_SIGNAL)

    det = DetectorLogic(StreamableOnlyDataLogic(tmp_path)).with_device("det")
    det.add_readables([child], Format.CHILD)
    await det.prepare(TriggerInfo())

    # The data logic describes its stream, the child describes its signal
    desc = await det.describe()
    assert "child-counts" in desc
    assert "det" in desc

    reading = await det.read()
    assert "child-counts" in reading
    assert reading["child-counts"]["value"] == 99


async def test_child_readable_hints_merged(tmp_path):
    """Child StandardReadable hints are merged with data logic hints."""
    child = StandardReadable(name="child")
    hinted_sig = soft_signal_rw(float, name="child-intensity")
    child.add_readables([hinted_sig], Format.HINTED_SIGNAL)

    det = DetectorLogic(StreamableOnlyDataLogic(tmp_path)).with_device("det")
    det.add_readables([child], Format.CHILD)

    assert "fields" in det.hints
    assert "child-intensity" in det.hints["fields"]
    assert "det" in det.hints["fields"]


async def test_trigger_logic_not_implemented_errors():
    """Test NotImplementedError for unimplemented DetectorTriggerLogic methods."""
    logic = DetectorTriggerLogic()

    with pytest.raises(NotImplementedError):
        logic.get_deadtime(SignalDict())

    with pytest.raises(NotImplementedError):
        await logic.prepare_internal(1, 0.1, 0.01)

    with pytest.raises(NotImplementedError):
        await logic.prepare_edge(1, 0.1)

    with pytest.raises(NotImplementedError):
        await logic.prepare_level(1)

    with pytest.raises(NotImplementedError):
        await logic.prepare_exposures_per_collection(2)


async def test_data_logic_not_implemented_errors():
    """Test NotImplementedError for unimplemented DetectorDataLogic methods."""
    logic = DetectorDataLogic()

    with pytest.raises(NotImplementedError):
        await logic.make_data_provider("test", 1, 0.1)

    # start() and stop() should not raise (they have default implementations)
    await logic.start()
    await logic.stop()


async def test_detector_readable_format_changes_at_runtime():
    # A StandardDetector is a StandardReadable, so a plugin signal can be moved
    # between configuration and hinted reads without redefining the Device.
    det = DetectorLogic().with_device("det")
    det.temperature, _ = soft_signal_r_and_setter(float, 20.0, name="temperature")

    name = det.temperature.name
    det.set_readable_format(det.temperature, Format.CONFIG_SIGNAL)
    assert set(await det.read_configuration()) == {name}
    # Empty hints are {} rather than {"fields": []}, as for any StandardReadable
    assert det.hints == {}

    det.set_readable_format(det.temperature, Format.HINTED_UNCACHED_SIGNAL)
    assert set(await det.read_configuration()) == set()
    assert det.hints == {"fields": [name]}

    det.set_readable_format(det.temperature, None)
    assert set(await det.read_configuration()) == set()
    assert det.hints == {}


async def test_detector_add_config_signals_is_deprecated():
    det = DetectorLogic().with_device("det")
    signal, _ = soft_signal_r_and_setter(float, 1.0, name="sig")
    with pytest.deprecated_call():
        det.add_config_signals(signal)
    assert set(await det.read_configuration()) == {signal.name}


async def test_streamable_logic_looks_like_writes_stream_assets(tmp_path):
    """An unbounded logic exposes collect_asset_docs, and only that.

    The bluesky bundler picks up stream assets via a structural isinstance
    against WritesStreamAssets (a hasattr check for collect_asset_docs). A
    detector must look like exactly one of WritesStreamAssets /
    EventPageCollectable so the bundler routes it down a single path.
    """
    det = DetectorLogic(StreamableOnlyDataLogic(tmp_path)).with_device()

    # Which verb applies follows what the logics will produce, so it is not
    # known until they have been asked
    assert not isinstance(det, WritesStreamAssets)
    await det.prepare(TriggerInfo())

    assert isinstance(det, WritesStreamAssets)
    assert not isinstance(det, EventPageCollectable)
    assert hasattr(det, "collect_asset_docs")
    assert not hasattr(det, "collect_pages")


async def test_bounded_logic_looks_like_event_page_collectable():
    """A bounded logic exposes collect_pages, and only that."""
    det = DetectorLogic(BoundedOnlyDataLogic()).with_device()
    await det.prepare(TriggerInfo())

    assert isinstance(det, EventPageCollectable)
    assert not isinstance(det, WritesStreamAssets)
    assert hasattr(det, "collect_pages")
    assert not hasattr(det, "collect_asset_docs")

    # An unbounded scan drops the finite buffer, so the verb goes with it
    await det.prepare(TriggerInfo(number_of_events=0))
    assert not isinstance(det, EventPageCollectable)
    assert not hasattr(det, "collect_pages")


async def test_no_data_logic_looks_like_neither():
    """A detector with no data logic emits neither stream assets nor event pages."""
    det = DetectorLogic(JustInternalTriggerLogic()).with_device()

    assert not isinstance(det, WritesStreamAssets)
    assert not isinstance(det, EventPageCollectable)
    assert not hasattr(det, "collect_asset_docs")
    assert not hasattr(det, "collect_pages")


async def test_missing_attribute_raises_standard_attribute_error():
    """__getattr__ falls through to a normal AttributeError for other names."""
    det = DetectorLogic().with_device()
    with pytest.raises(
        AttributeError,
        match=r"object has no attribute 'does_not_exist'",
    ):
        det.does_not_exist  # noqa: B018


async def test_unshadowed_bounded_keys_raise(tmp_path):
    """A finite buffer the stream assets do not cover cannot be combined with them."""
    det = DetectorLogic(
        BoundedOnlyDataLogic(datakey_suffix="-stats"), StreamableOnlyDataLogic(tmp_path)
    ).with_device("det")

    # Only knowable once the logics have said what they would make
    with pytest.raises(
        TypeError,
        match=(
            r"would produce \['det-stats'\] as event pages and the rest of its "
            r"data as stream assets"
        ),
    ):
        await det.prepare(TriggerInfo())


async def test_shadowed_bounded_logic_sits_the_scan_out(tmp_path):
    """A finite buffer whose keys are all written durably gives way to the file."""
    bounded = BoundedOnlyDataLogic()
    det = DetectorLogic(bounded, StreamableOnlyDataLogic(tmp_path)).with_device("det")

    await det.prepare(TriggerInfo())

    # Both would produce "det", so the durable copy wins and nothing was armed
    assert bounded.prepare_calls == []
    assert det.logic.data is not None
    assert det.logic.data.pageable == []
    assert isinstance(det, WritesStreamAssets)
    assert not isinstance(det, EventPageCollectable)
    # ...and it stops hinting at data nobody will produce
    assert det.hints == {"fields": ["det"]}
