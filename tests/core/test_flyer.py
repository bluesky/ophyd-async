import time
from enum import Enum
from typing import Any, AsyncGenerator, AsyncIterator, Dict, Optional, Sequence
from unittest.mock import Mock

import bluesky.plan_stubs as bps
import pytest
from bluesky.protocols import DataKey, StreamAsset
from bluesky.run_engine import RunEngine
from event_model import ComposeStreamResourceBundle, compose_stream_resource

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorControl,
    DetectorTrigger,
    DetectorWriter,
    HardwareTriggeredFlyable,
    TriggerInfo,
    TriggerLogic,
)
from ophyd_async.core.detector import StandardDetector
from ophyd_async.core.signal import observe_value
from ophyd_async.epics.signal.signal import epics_signal_rw


class TriggerState(str, Enum):
    null = "null"
    preparing = "preparing"
    starting = "starting"
    stopping = "stopping"


class DummyTriggerLogic(TriggerLogic[int]):
    def __init__(self):
        self.state = TriggerState.null

    async def prepare(self, value: int):
        self.state = TriggerState.preparing
        return value

    async def kickoff(self):
        self.state = TriggerState.starting

    async def complete(self):
        self.state = TriggerState.null

    async def stop(self):
        self.state = TriggerState.stopping


class DummyWriter(DetectorWriter):
    def __init__(self, name: str, shape: Sequence[int]):
        self.dummy_signal = epics_signal_rw(int, "pva://read_pv")
        self._shape = shape
        self._name = name
        self._file: Optional[ComposeStreamResourceBundle] = None
        self._last_emitted = 0
        self.index = 0

    async def open(self, multiplier: int = 1) -> Dict[str, DataKey]:
        return {
            self._name: DataKey(
                source="soft://some-source",
                shape=self._shape,
                dtype="number",
                external="STREAM:",
            )
        }

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        num_captured: int
        async for num_captured in observe_value(self.dummy_signal, timeout):
            yield num_captured

    async def get_indices_written(self) -> int:
        return self.index

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        if indices_written:
            if not self._file:
                self._file = compose_stream_resource(
                    mimetype="application/x-hdf5",
                    uri="",
                    data_key=self._name,
                    parameters={
                        "path": "",
                        "dataset": "",
                        "multiplier": False,
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

    async def dummy_arm_1(self=None, trigger=None, num=0, exposure=None):
        return writers[0].dummy_signal.set(1)

    async def dummy_arm_2(self=None, trigger=None, num=0, exposure=None):
        return writers[1].dummy_signal.set(1)

    detector_1: StandardDetector[Any] = StandardDetector(
        Mock(spec=DetectorControl, get_deadtime=lambda num: num, arm=dummy_arm_1),
        writers[0],
        name="detector_1",
    )
    detector_2: StandardDetector[Any] = StandardDetector(
        Mock(spec=DetectorControl, get_deadtime=lambda num: num, arm=dummy_arm_2),
        writers[1],
        name="detector_2",
    )

    return (detector_1, detector_2)


async def test_hardware_triggered_flyable(
    RE: RunEngine, detectors: tuple[StandardDetector]
):
    names = []
    docs = []

    def append_and_print(name, doc):
        names.append(name)
        docs.append(doc)

    RE.subscribe(append_and_print)

    trigger_logic = DummyTriggerLogic()
    flyer = HardwareTriggeredFlyable(trigger_logic, [], name="flyer")
    trigger_info = TriggerInfo(
        num=1, trigger=DetectorTrigger.constant_gate, deadtime=2, livetime=2
    )

    def flying_plan():
        yield from bps.stage_all(*detectors, flyer)
        assert flyer._trigger_logic.state == TriggerState.stopping

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

        assert flyer._trigger_logic.state == TriggerState.preparing
        for detector in detectors:
            detector.controller.disarm.assert_called_once  # type: ignore

        yield from bps.open_run()
        yield from bps.declare_stream(*detectors, name="main_stream", collect=True)

        yield from bps.kickoff(flyer)
        for detector in detectors:
            yield from bps.kickoff(detector)

        yield from bps.complete(flyer, wait=False, group="complete")
        for detector in detectors:
            yield from bps.complete(detector, wait=False, group="complete")
        assert flyer._trigger_logic.state == TriggerState.null

        # Manually incremenet the index as if a frame was taken
        for detector in detectors:
            detector.writer.index += 1

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
        yield from bps.close_run()

        yield from bps.unstage_all(flyer, *detectors)
        for detector in detectors:
            assert detector.controller.disarm.called  # type: ignore
        assert trigger_logic.state == TriggerState.stopping

    # fly scan
    RE(flying_plan())

    assert names == [
        "start",
        "descriptor",
        "stream_resource",
        "stream_datum",
        "stream_resource",
        "stream_datum",
        "stop",
    ]


# To do: Populate configuration signals
async def test_describe_configuration():
    flyer = HardwareTriggeredFlyable(DummyTriggerLogic(), [], name="flyer")
    assert await flyer.describe_configuration() == {}


# To do: Populate configuration signals
async def test_read_configuration():
    flyer = HardwareTriggeredFlyable(DummyTriggerLogic(), [], name="flyer")
    assert await flyer.read_configuration() == {}
