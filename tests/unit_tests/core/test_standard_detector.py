import asyncio
import re
from collections.abc import Sequence
from unittest.mock import ANY

import numpy as np
import pytest

from ophyd_async.core import (
    Array1D,
    DetectorArmLogic,
    DetectorDataLogic,
    DetectorTrigger,
    DetectorTriggerLogic,
    ReadableDataProvider,
    Settings,
    SignalDataProvider,
    SignalDict,
    SignalR,
    StandardDetector,
    StreamableDataProvider,
    StreamResourceDataProvider,
    StreamResourceInfo,
    TriggerInfo,
    soft_signal_rw,
)
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

    def config_sigs(self) -> set[SignalR]:
        """Return the deadtime signal as a config signal."""
        return {self.deadtime_signal}

    def get_deadtime(self, config_values: SignalDict) -> float:
        """Return the deadtime from the signal value."""
        return config_values[self.deadtime_signal]

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        self.num, self.livetime, self.deadtime = num, livetime, deadtime


class MockArmLogic(DetectorArmLogic):
    """Mock arm logic that tracks state."""

    armed = False
    arm_count = 0
    disarm_count = 0

    async def arm(self):
        self.armed = True
        self.arm_count += 1

    async def wait_for_idle(self):
        await asyncio.sleep(0.001)
        self.armed = False

    async def disarm(self):
        self.armed = False
        self.disarm_count += 1


class ReadableOnlyDataLogic(DetectorDataLogic):
    """Produces only readable (non-streaming) data."""

    def __init__(self):
        self.signal = soft_signal_rw(int, initial_value=42, name="foo-value")

    async def prepare_single(self, detector_name: str) -> ReadableDataProvider:
        return SignalDataProvider(self.signal)

    def get_hinted_fields(self, detector_name: str) -> Sequence[str]:
        return ["foo-value"]


class StreamableOnlyDataLogic(DetectorDataLogic):
    """Produces only streamable (file-based) data."""

    def __init__(self, tmp_path):
        self.collections_written = soft_signal_rw(int)
        self.stop_count = 0
        self.tmp_path = tmp_path

    async def prepare_unbounded(self, detector_name: str) -> StreamableDataProvider:
        resource = StreamResourceInfo(
            data_key=detector_name,
            shape=(10, 15),
            chunk_shape=(1, 10, 15),
            dtype_numpy="|u1",
            parameters={"dataset": "/data"},
        )
        provider = StreamResourceDataProvider(
            uri=f"file://localhost{self.tmp_path.as_posix()}/test.h5",
            resources=[resource],
            mimetype="application/x-hdf5",
            collections_written_signal=self.collections_written,
        )
        return provider

    async def stop(self) -> None:
        self.stop_count += 1

    def get_hinted_fields(self, detector_name: str) -> Sequence[str]:
        return [detector_name]


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
    det = StandardDetector()
    if trigger_logic:
        det.add_logics(trigger_logic)
    triggers, deadtime = await det.get_trigger_deadtime()
    assert triggers == expected_triggers
    assert deadtime == expected_deadtime


async def test_get_trigger_deadtime_with_settings():
    """Test get_trigger_deadtime using values from a Settings object."""
    # Create a signal for deadtime and set its initial value
    deadtime_signal = soft_signal_rw(float, 0.02)

    # Create detector with DeadtimeTriggerLogic
    det = StandardDetector()
    det.sig = deadtime_signal
    tl = DeadtimeTriggerLogic(deadtime_signal)
    det.add_logics(tl)

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
    det = StandardDetector()
    trigger_logic = AllTriggerTypesLogic()
    det.add_logics(trigger_logic)

    trigger_info = TriggerInfo(
        trigger=trigger_type, livetime=0.5, deadtime=0.1, number_of_events=10
    )
    await det.prepare(trigger_info)

    # Verify the right prepare method was called
    assert trigger_logic.trigger == trigger_type
    assert trigger_logic.num == 10


async def test_prepare_unsupported_trigger_type():
    """Test that preparing with unsupported trigger type raises error."""
    det = StandardDetector()
    det.add_logics(JustInternalTriggerLogic())

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
    det = StandardDetector()
    tl = AveragingTriggerLogic()
    det.add_logics(tl)

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
    det = StandardDetector()
    det.add_logics(JustInternalTriggerLogic())  # Doesn't support averaging

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
    det = StandardDetector()
    tl = AllTriggerTypesLogic()
    al = MockArmLogic()
    dl = StreamableOnlyDataLogic(tmp_path)
    det.add_logics(tl, al, dl)

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
    det = StandardDetector()
    al = MockArmLogic()
    dl = StreamableOnlyDataLogic(tmp_path)
    det.add_logics(JustInternalTriggerLogic(), al, dl)

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
    """Test that arm logic is disarmed on stage."""
    det = StandardDetector()
    al = MockArmLogic()
    det.add_logics(al)

    al.armed = True  # Simulate being armed
    await det.stage()

    assert al.disarm_count == 1
    assert al.armed is False


async def test_describe_before_prepare_raises():
    """Test that describe() fails before prepare()."""
    det = StandardDetector()
    det.add_logics(ReadableOnlyDataLogic())

    with pytest.raises(RuntimeError, match="Prepare not run"):
        await det.describe()


async def test_describe_collect_before_prepare_raises(tmp_path):
    """Test that describe_collect() fails before prepare()."""
    det = StandardDetector()
    det.add_logics(StreamableOnlyDataLogic(tmp_path))

    with pytest.raises(RuntimeError, match="Prepare not run"):
        await det.describe_collect()


async def test_trigger_after_multi_event_prepare_raises():
    """Test that trigger() after prepare with multiple events fails."""
    det = StandardDetector()
    det.add_logics(JustInternalTriggerLogic())

    await det.prepare(TriggerInfo(number_of_events=5))

    with pytest.raises(ValueError, match="trigger\\(\\) is not supported for multiple"):
        await det.trigger()


async def test_kickoff_respects_prepare_bounds(tmp_path):
    """Test that multiple kickoff() calls respect prepared bounds."""
    det = StandardDetector()
    tl = JustInternalTriggerLogic()
    dl = StreamableOnlyDataLogic(tmp_path)
    det.add_logics(tl, dl)

    # Prepare for 5 events
    await det.prepare(TriggerInfo(number_of_events=5))

    # Update collections_written signal to simulate data being written

    # First kickoff for 3 events
    await det.events_to_kickoff.set(3)
    await det.kickoff()
    await dl.collections_written.set(3)

    # Second kickoff for 2 events should work (total = 5)
    await det.events_to_kickoff.set(2)
    await det.kickoff()
    await dl.collections_written.set(5)

    # Third kickoff should fail (would exceed 5)
    await det.events_to_kickoff.set(1)
    with pytest.raises(
        RuntimeError,
        match="Kickoff requested 5:6, but detector was only prepared up to 5",
    ):
        await det.kickoff()


async def test_stage_resets_state():
    """Test that stage() resets detector state."""
    det = StandardDetector()
    det.add_logics(JustInternalTriggerLogic())

    await det.prepare(TriggerInfo(number_of_events=5))
    await det.events_to_kickoff.set(3)

    # Stage should reset everything
    await det.stage()

    assert det._prepare_ctx is None
    assert det._kickoff_ctx is None
    assert await det.events_to_kickoff.get_value() == 0


async def test_hints_from_single_data_logic():
    """Test that hints come from data logic."""
    det = StandardDetector()
    det.add_logics(ReadableOnlyDataLogic())

    await det.prepare(TriggerInfo())

    assert det.hints == {
        "fields": ["foo-value"]
    }  # ReadableOnlyDataLogic uses foo-value


async def test_hints_from_multiple_data_logics(tmp_path):
    """Test that hints are aggregated from multiple data logics."""
    det = StandardDetector(name="bar")
    dl1 = ReadableOnlyDataLogic()
    dl2 = StreamableOnlyDataLogic(tmp_path)
    det.add_logics(dl1, dl2)

    await det.prepare(TriggerInfo())

    # Should include hints from both logics
    hints = det.hints
    assert "fields" in hints
    assert hints["fields"] == ["foo-value", "bar"]


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
    det = StandardDetector()
    signal = soft_signal_rw(
        signal_type, initial_value=initial_value, name="test-config"
    )
    det.add_config_signals(signal)

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
    det = StandardDetector(name="foo")
    det.add_logics(JustInternalTriggerLogic(), ReadableOnlyDataLogic())

    # Single event prepare for readable-only logic
    await det.prepare(TriggerInfo())
    await det.trigger()  # This works

    # Readable-only logic doesn't support kickoff
    await det.prepare(TriggerInfo(number_of_events=5))
    with pytest.raises(
        ValueError, match="Detector foo is not streamable, so cannot kickoff"
    ):
        await det.kickoff()


async def test_streamable_supports_both_step_and_fly(tmp_path):
    """Test that streamable data logic supports both step and fly scanning."""
    det = StandardDetector(name="foo")
    tl = JustInternalTriggerLogic()
    dl = StreamableOnlyDataLogic(tmp_path)
    det.add_logics(tl, dl)

    # Step scan should work
    status = det.trigger()
    # Yield so detector can get collections written, then set it so we complete
    await wait_for_pending_wakeups(raise_if_exceeded=False)
    await dl.collections_written.set(1)
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
                "uri": f"file://localhost{tmp_path.as_posix()}/test.h5",
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
    assert status.done
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
    """Test that read() returns values from readable providers."""
    det = StandardDetector(name="det")
    dl = ReadableOnlyDataLogic()
    det.add_logics(dl)

    await det.trigger()
    await assert_reading(det, {"foo-value": {"value": 42}})


async def test_detector_with_no_logics():
    """Test that detector works with no logics for basic internal triggering."""
    det = StandardDetector()

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
    det = StandardDetector(name="foo")
    msg = "Detector foo has no trigger logic, so "

    with pytest.raises(ValueError, match=msg + "cannot set livetime or deadtime"):
        await det.prepare(TriggerInfo(livetime=0.5))

    with pytest.raises(ValueError, match=msg + "cannot set livetime or deadtime"):
        await det.prepare(TriggerInfo(deadtime=0.1))


async def test_cannot_add_two_trigger_logics():
    """Test that adding two trigger logics raises an error."""
    det = StandardDetector()
    tl1 = JustInternalTriggerLogic()
    tl2 = AllTriggerTypesLogic()

    det.add_logics(tl1)

    with pytest.raises(RuntimeError, match="Detector already has trigger logic"):
        det.add_logics(tl2)


async def test_cannot_add_two_arm_logics():
    """Test that adding two arm logics raises an error."""
    det = StandardDetector()
    al1 = MockArmLogic()
    al2 = MockArmLogic()

    det.add_logics(al1)

    with pytest.raises(RuntimeError, match="Detector already has arm logic"):
        det.add_logics(al2)


async def test_add_unknown_logic_type_raises():
    """Test that adding an unknown logic type raises TypeError."""
    det = StandardDetector()

    class UnknownLogic:
        pass

    with pytest.raises(TypeError, match="Unknown logic type"):
        det.add_logics(UnknownLogic())


async def test_multiple_collections_with_single_only_logic_raises():
    """Test that requesting multiple collections fails with single-only data logic."""
    det = StandardDetector()
    det.add_logics(ReadableOnlyDataLogic())

    with pytest.raises(RuntimeError, match="Multiple collections not supported"):
        await det.prepare(TriggerInfo(number_of_events=5))


async def test_data_logic_with_no_prepare_methods_raises():
    """Test error when DataLogic doesn't override any prepare methods."""

    class EmptyDataLogic(DetectorDataLogic):
        pass

    det = StandardDetector()
    det.add_logics(EmptyDataLogic())

    with pytest.raises(RuntimeError, match="hasn't overridden any prepare_\\* methods"):
        await det.prepare(TriggerInfo())


async def test_unstage_disarms_detector():
    """Test that unstage() calls disarm on the detector."""
    det = StandardDetector()
    al = MockArmLogic()
    det.add_logics(al)

    al.armed = True
    await det.unstage()

    assert al.disarm_count == 1
    assert al.armed is False


async def test_prepare_stops_data_logic_when_recreating_providers(tmp_path):
    """Test that prepare() calls stop() on data logic when recreating providers."""
    det = StandardDetector(name="det")
    dl = StreamableOnlyDataLogic(tmp_path)
    det.add_logics(JustInternalTriggerLogic(), dl)

    # First prepare with collections_per_event=2
    await det.prepare(TriggerInfo(number_of_events=3, collections_per_event=2))
    assert dl.stop_count == 0  # No stop on first prepare

    # Second prepare with different collections_per_event triggers recreation
    await det.prepare(TriggerInfo(number_of_events=3, collections_per_event=3))
    assert dl.stop_count == 1  # stop() should have been called


async def test_different_collections_written_raises(tmp_path):
    """Test that different collections_written values from providers raises error."""
    det = StandardDetector(name="det")
    dl1 = StreamableOnlyDataLogic(tmp_path)
    dl2 = StreamableOnlyDataLogic(tmp_path)
    det.add_logics(JustInternalTriggerLogic(), dl1, dl2)

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


async def test_multiple_data_logics(tmp_path):
    """Test detector with multiple data logics."""
    det = StandardDetector(name="det")
    dl1 = ReadableOnlyDataLogic()
    dl2 = StreamableOnlyDataLogic(tmp_path)
    det.add_logics(JustInternalTriggerLogic(), dl1, dl2)

    await det.prepare(TriggerInfo())

    # Should have data from both logics
    description = await det.describe()
    assert description == {
        "det": {
            "dtype": "array",
            "dtype_numpy": "|u1",
            "external": "STREAM:",
            "shape": [1, 10, 15],
            "source": f"file://localhost{tmp_path.as_posix()}/test.h5",
        },
        "foo-value": {
            "dtype": "integer",
            "dtype_numpy": "<i8",
            "shape": [],
            "source": "soft://foo-value",
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
            "source": f"file://localhost{tmp_path.as_posix()}/test.h5",
        },
    }
    # Should be able to do fly scanning (has streamable logic)
    await det.prepare(TriggerInfo(number_of_events=3))
    await det.kickoff()


async def test_collect_asset_docs_with_explicit_index(tmp_path):
    """Test collect_asset_docs() with explicitly provided index."""
    det = StandardDetector(name="det")
    dl = StreamableOnlyDataLogic(tmp_path)
    det.add_logics(JustInternalTriggerLogic(), dl)

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
                "uri": f"file://localhost{tmp_path.as_posix()}/test.h5",
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
        await logic.prepare_single("test")

    with pytest.raises(NotImplementedError):
        await logic.prepare_unbounded("test")

    # stop() should not raise (has default implementation)
    await logic.stop()  # Should pass
