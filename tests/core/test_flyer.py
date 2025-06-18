import asyncio
import time
from collections import defaultdict
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from typing import Any
from unittest.mock import Mock

import bluesky.plan_stubs as bps
import pytest
from bluesky.protocols import StreamAsset
from bluesky.run_engine import RunEngine
from event_model import (  # type: ignore
    ComposeStreamResourceBundle,
    DataKey,
    compose_stream_resource,
)
from pydantic import ValidationError

from ophyd_async.core import (
    DetectorController,
    DetectorTrigger,
    DetectorWriter,
    FlyerController,
    StandardDetector,
    StandardFlyer,
    StrictEnum,
    TriggerInfo,
    observe_value,
)
from ophyd_async.epics.core import epics_signal_rw
from ophyd_async.testing import assert_emitted


class TriggerState(StrictEnum):
    NULL = "null"
    PREPARING = "preparing"
    STARTING = "starting"
    STOPPING = "stopping"


class DummyTriggerLogic(FlyerController[int]):
    def __init__(self):
        self.state = TriggerState.NULL

    async def prepare(self, value: int):
        self.state = TriggerState.PREPARING
        return value

    async def kickoff(self):
        self.state = TriggerState.STARTING

    async def complete(self):
        self.state = TriggerState.NULL

    async def stop(self):
        self.state = TriggerState.STOPPING


class DummyWriter(DetectorWriter):
    def __init__(self, name: str, shape: Sequence[int]):
        self.dummy_signal = epics_signal_rw(int, "pva://read_pv")
        self._shape = shape
        self._name = name
        self._file: ComposeStreamResourceBundle | None = None
        self._last_emitted = 0
        self.index = 0

    async def open(self, name: str, exposures_per_event: int = 1) -> dict[str, DataKey]:
        self._exposures_per_event = exposures_per_event
        return {
            self._name: DataKey(
                source="soft://some-source",
                shape=[exposures_per_event, *self._shape],
                dtype="number",
                dtype_numpy="<u2",
                external="STREAM:",
            )
        }

    async def observe_indices_written(
        self, timeout: float
    ) -> AsyncGenerator[int, None]:
        num_captured: int
        async for num_captured in observe_value(self.dummy_signal, timeout):
            yield num_captured // self._exposures_per_event

    async def get_indices_written(self) -> int:
        return self.index // self._exposures_per_event

    async def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        if indices_written:
            if not self._file:
                self._file = compose_stream_resource(
                    mimetype="application/x-hdf5",
                    uri="file://",
                    data_key=self._name,
                    parameters={
                        "path": "",
                        "dataset": "",
                    },
                    uid=None,
                    validate=True,
                )
                yield "stream_resource", self._file.stream_resource_doc

            if indices_written >= self._last_emitted:
                indices = {
                    "start": self._last_emitted,
                    "stop": indices_written,
                }
                self._last_emitted = indices_written
                self._last_flush = time.monotonic()
                yield "stream_datum", self._file.compose_stream_datum(indices)

    async def close(self) -> None:
        self._file = None


@pytest.fixture
async def detectors(RE: RunEngine) -> tuple[StandardDetector, StandardDetector]:
    writers = [DummyWriter("testa", (1, 1)), DummyWriter("testb", (1, 1))]
    await writers[0].dummy_signal.connect(mock=True)
    await writers[1].dummy_signal.connect(mock=True)

    def dummy_arm_1(self=None, trigger=None, num=0, exposure=None):
        return writers[0].dummy_signal.set(1)

    async def dummy_arm_2(self=None, trigger=None, num=0, exposure=None):
        return writers[1].dummy_signal.set(1)

    detector_1: StandardDetector[Any, Any] = StandardDetector(
        Mock(spec=DetectorController, get_deadtime=lambda num: num, arm=dummy_arm_1),
        writers[0],
        name="detector_1",
    )
    detector_2: StandardDetector[Any, Any] = StandardDetector(
        Mock(spec=DetectorController, get_deadtime=lambda num: num, arm=dummy_arm_2),
        writers[1],
        name="detector_2",
    )

    return (detector_1, detector_2)


@pytest.mark.parametrize(
    "number_of_triggers", [[1, 2, 3, 4], [2, 3, 100, 3], [1, 1, 1, 1]]
)
async def test_hardware_triggered_flyable(
    RE: RunEngine, detectors: tuple[StandardDetector], number_of_triggers: list[int]
):
    docs = defaultdict(list)
    RE.subscribe(lambda name, doc: docs[name].append(doc))

    trigger_logic = DummyTriggerLogic()
    flyer = StandardFlyer(trigger_logic, name="flyer")

    def flying_plan():
        yield from bps.stage_all(*detectors, flyer)
        assert flyer._trigger_logic.state == TriggerState.STOPPING

        # move the flyer to the correct place, before fly scanning.
        # Prepare the flyer first to get the trigger info for the detectors
        yield from bps.prepare(flyer, 1, wait=True)

        # prepare detectors second.
        for detector in detectors:
            yield from bps.prepare(
                detector,
                TriggerInfo(
                    number_of_events=number_of_triggers,
                    trigger=DetectorTrigger.CONSTANT_GATE,
                    deadtime=2,
                    livetime=2,
                ),
                wait=True,
            )

        assert flyer._trigger_logic.state == TriggerState.PREPARING
        for detector in detectors:
            detector._controller.disarm.assert_called_once()  # type: ignore

        yield from bps.open_run()
        yield from bps.declare_stream(*detectors, name="main_stream", collect=True)
        frames_completed: int = 0
        for frames in number_of_triggers:
            yield from bps.kickoff(flyer)
            for detector in detectors:
                yield from bps.kickoff(detector)

            yield from bps.complete(flyer, wait=False, group="complete")
            for detector in detectors:
                yield from bps.complete(detector, wait=False, group="complete")

            assert flyer._trigger_logic.state == TriggerState.NULL

            # Manually increment the index as if a frame was taken
            frames_completed += frames
            for detector in detectors:
                yield from bps.abs_set(detector._writer.dummy_signal, frames_completed)
                detector._writer.index = frames_completed
            done = False
            while not done:
                try:
                    yield from bps.wait(group="complete", timeout=0.5)
                except TimeoutError:
                    pass
                else:
                    done = True

                    yield from bps.collect(
                        *detectors,
                        return_payload=False,
                        name="main_stream",
                    )
            yield from bps.wait(group="complete")

        for detector in detectors:
            # ensure _completable_frames are reset after completion
            assert detector._completable_exposures == 0

        yield from bps.close_run()

        yield from bps.unstage_all(flyer, *detectors)
        for detector in detectors:
            assert detector._controller.disarm.called  # type: ignore
        assert trigger_logic.state == TriggerState.STOPPING

    # fly scan
    RE(flying_plan())

    assert_emitted(
        docs,
        start=1,
        descriptor=1,
        stream_resource=2,
        stream_datum=2 * len(number_of_triggers),
        stop=1,
    )
    # test stream datum
    seq_numbers: list = []
    frame_completed: int = 0
    last_frame_collected: int = 0
    for frame in number_of_triggers:
        frame_completed += frame
        seq_numbers.extend([(last_frame_collected, frame_completed)] * 2)
        last_frame_collected = frame_completed
    for index, stream_datum in enumerate(docs["stream_datum"]):
        assert stream_datum["descriptor"] == docs["descriptor"][0]["uid"]
        assert stream_datum["seq_nums"] == {
            "start": seq_numbers[index][0] + 1,
            "stop": seq_numbers[index][1] + 1,
        }
        assert stream_datum["indices"] == {
            "start": seq_numbers[index][0],
            "stop": seq_numbers[index][1],
        }
        assert stream_datum["stream_resource"] in [
            sd["uid"].split("/")[0] for sd in docs["stream_datum"]
        ]


@pytest.mark.timeout(3.0)
@pytest.mark.parametrize(
    "number_of_triggers,invoke_extra_kickoff_before_complete",
    [
        (10, True),
        ([10], True),
        (10, False),
        ([10], False),
    ],
)
async def test_hardware_triggered_flyable_too_many_kickoffs(
    RE: RunEngine,
    detectors: tuple[StandardDetector],
    number_of_triggers: int | list[int],
    invoke_extra_kickoff_before_complete: bool,
):
    trigger_logic = DummyTriggerLogic()
    flyer = StandardFlyer(trigger_logic, name="flyer")
    trigger_info = TriggerInfo(
        number_of_events=number_of_triggers,
        trigger=DetectorTrigger.CONSTANT_GATE,
        deadtime=2,
        livetime=2,
    )

    def flying_plan():
        yield from bps.stage_all(*detectors, flyer)
        assert flyer._trigger_logic.state == TriggerState.STOPPING

        # move the flyer to the correct place, before fly scanning.
        # Prepare the flyer first to get the trigger info for the detectors
        yield from bps.prepare(flyer, 1, wait=True)

        # prepare detectors second.
        for detector in detectors:
            yield from bps.prepare(
                detector,
                trigger_info,
                wait=True,
            )

        yield from bps.open_run()
        yield from bps.declare_stream(*detectors, name="main_stream", collect=True)

        yield from bps.kickoff(flyer)
        for detector in detectors:
            yield from bps.kickoff(detector)
            # Perform an additional kickoff
            if invoke_extra_kickoff_before_complete:
                yield from bps.kickoff(detector)
        yield from bps.complete(flyer, wait=False, group="complete")
        for detector in detectors:
            yield from bps.complete(detector, wait=False, group="complete")

        assert flyer._trigger_logic.state == TriggerState.NULL

        # Manually increment the index as if a frame was taken
        for detector in detectors:
            yield from bps.abs_set(
                detector._writer.dummy_signal, trigger_info.total_number_of_exposures
            )
            detector._writer.index = trigger_info.total_number_of_exposures

        yield from bps.wait(group="complete")

        yield from bps.collect(
            *detectors,
            return_payload=False,
            name="main_stream",
        )

        for detector in detectors:
            # Since we set number of iterations to 1 (default),
            # make sure it gets reset on complete
            assert detector._completable_exposures == 0
            assert detector._events_to_complete == 0
            assert detector._number_of_events_iter is None
            assert detector._controller.wait_for_idle.called  # type: ignore

            # This is an additional kickoff
            # Ensuring stop iteration is called if kickoff is invoked after complete
            if not invoke_extra_kickoff_before_complete:
                yield from bps.kickoff(detector)
        yield from bps.close_run()

        yield from bps.unstage_all(flyer, *detectors)

    # fly scan
    if invoke_extra_kickoff_before_complete:
        match_msg = "Kickoff called more than the configured number"
    else:
        match_msg = "Prepare must be called before kickoff!"
    with pytest.raises(Exception, match=match_msg):
        RE(flying_plan())

    # Try explicitly letting event loop clean up tasks...?
    await asyncio.sleep(1.0)


@pytest.mark.parametrize(
    ["kwargs", "error_msg"],
    [
        (
            {
                "number_of_events": 1,
                "trigger": DetectorTrigger.CONSTANT_GATE,
                "deadtime": 2,
                "livetime": 2,
                "exposure_timeout": "a",
            },
            "Input should be a valid number, unable to parse string as a number "
            "[type=float_parsing, input_value='a', input_type=str]",
        ),
        (
            {
                "number_of_events": 1,
                "trigger": "CONSTANT_GATE",
                "deadtime": 2,
                "livetime": -1,
            },
            "Input should be greater than or equal to 0 "
            "[type=greater_than_equal, input_value=-1, input_type=int]",
        ),
        (
            {
                "number_of_events": 1,
                "trigger": DetectorTrigger.INTERNAL,
                "deadtime": 2,
                "livetime": 1,
                "exposure_timeout": -1,
            },
            "Input should be greater than 0 "
            "[type=greater_than, input_value=-1, input_type=int]",
        ),
        (
            {
                "number_of_events": 1,
                "trigger": "not_in_enum",
                "deadtime": 2,
                "livetime": 1,
                "exposure_timeout": None,
            },
            "Input should be 'INTERNAL', 'EDGE_TRIGGER', 'CONSTANT_GATE' or "
            "'VARIABLE_GATE' [type=enum, input_value='not_in_enum', input_type=str]",
        ),
        (
            {
                "number_of_events": -100,
                "trigger": "CONSTANT_GATE",
                "deadtime": 2,
                "livetime": 1,
            },
            "number_of_events.constrained-int\n  Input should be greater than or "
            "equal to 0 [type=greater_than_equal, input_value=-100, input_type=int]",
        ),
        (
            {
                "number_of_events": [1, 1, 1, 1, -100],
                "trigger": "CONSTANT_GATE",
                "deadtime": 2,
                "livetime": 1,
            },
            "number_of_events.list[constrained-int].4\n"
            "  Input should be greater than or equal to 0 [type=greater_than_equal,"
            " input_value=-100, input_type=int]\n",
        ),
    ],
)
def test_malformed_trigger_info(kwargs, error_msg):
    with pytest.raises(ValidationError) as exc:
        TriggerInfo(**kwargs)
    assert error_msg in str(exc.value)
