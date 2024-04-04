import time
from typing import AsyncGenerator, AsyncIterator, Dict, Optional, Sequence
from unittest.mock import Mock

import bluesky.plan_stubs as bps
import pytest
from bluesky.protocols import Descriptor, StreamAsset
from bluesky.run_engine import RunEngine
from event_model import ComposeStreamResourceBundle, compose_stream_resource

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorControl,
    DetectorWriter,
    HardwareTriggeredFlyable,
    SignalRW,
    SimSignalBackend,
)
from ophyd_async.core.detector import StandardDetector
from ophyd_async.core.device import DeviceCollector
from ophyd_async.core.signal import observe_value, set_sim_value
from ophyd_async.epics.pvi.pvi import fill_pvi_entries
from ophyd_async.panda import CommonPandaBlocks
from ophyd_async.panda.trigger import StaticSeqTableTriggerLogic
from ophyd_async.planstubs import (
    prepare_static_seq_table_flyer_and_detectors_with_same_trigger,
)


class DummyWriter(DetectorWriter):
    def __init__(self, name: str, shape: Sequence[int]):
        self.dummy_signal = SignalRW(backend=SimSignalBackend(int))
        self._shape = shape
        self._name = name
        self._file: Optional[ComposeStreamResourceBundle] = None
        self._last_emitted = 0
        self.index = 0

    async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        return {
            self._name: Descriptor(
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
                    spec="AD_HDF5_SWMR_SLICE",
                    root="/",
                    data_key=self._name,
                    resource_path="",
                    resource_kwargs={
                        "path": "",
                        "multiplier": 1,
                        "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
                    },
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
async def detector_list(RE: RunEngine) -> tuple[StandardDetector, StandardDetector]:
    writers = [DummyWriter("testa", (1, 1)), DummyWriter("testb", (1, 1))]
    await writers[0].dummy_signal.connect(sim=True)
    await writers[1].dummy_signal.connect(sim=True)

    async def dummy_arm_1(self=None, trigger=None, num=0, exposure=None):
        return writers[0].dummy_signal.set(1)

    async def dummy_arm_2(self=None, trigger=None, num=0, exposure=None):
        return writers[1].dummy_signal.set(1)

    detector_1: StandardDetector = StandardDetector(
        Mock(spec=DetectorControl, get_deadtime=lambda num: num, arm=dummy_arm_1),
        writers[0],
        name="detector_1",
        writer_timeout=3,
    )
    detector_2: StandardDetector = StandardDetector(
        Mock(spec=DetectorControl, get_deadtime=lambda num: num, arm=dummy_arm_2),
        writers[1],
        name="detector_2",
        writer_timeout=3,
    )
    return (detector_1, detector_2)


@pytest.fixture
async def panda():
    class Panda(CommonPandaBlocks):
        def __init__(self, prefix: str, name: str = ""):
            self._prefix = prefix
            super().__init__(name)

        async def connect(self, sim: bool = False, timeout: float = DEFAULT_TIMEOUT):
            await fill_pvi_entries(self, self._prefix + "PVI", timeout=timeout, sim=sim)
            await super().connect(sim, timeout)

    async with DeviceCollector(sim=True):
        sim_panda = Panda("PANDAQSRV:", "sim_panda")

    assert sim_panda.name == "sim_panda"
    yield sim_panda


async def test_hardware_triggered_flyable_with_static_seq_table_logic(
    RE: RunEngine,
    detector_list: tuple[StandardDetector],
    panda,
):
    """Run a dummy scan using a flyer with a prepare plan stub.

    This runs a dummy plan with two detectors and a flyer that uses
    StaticSeqTableTriggerLogic. The flyer and detectors are prepared with the
    prepare_static_seq_table_flyer_and_detectors_with_same_trigger plan stub.
    This stub creates trigger_info and a sequence table from given parameters
    and prepares the fly and both detectors with the same trigger info.

    """
    names = []
    docs = []

    def append_and_print(name, doc):
        names.append(name)
        docs.append(doc)

    RE.subscribe(append_and_print)

    shutter_time = 0.004
    exposure = 1
    deadtime = max(det.controller.get_deadtime(1) for det in detector_list)

    trigger_logic = StaticSeqTableTriggerLogic(panda.seq[1])
    flyer = HardwareTriggeredFlyable(trigger_logic, [], name="flyer")

    def flying_plan():
        yield from bps.stage_all(*detector_list, flyer)

        yield from prepare_static_seq_table_flyer_and_detectors_with_same_trigger(
            flyer,
            detector_list,
            num=1,
            width=exposure,
            deadtime=deadtime,
            shutter_time=shutter_time,
        )

        for detector in detector_list:
            detector.controller.disarm.assert_called_once  # type: ignore

        yield from bps.open_run()
        yield from bps.declare_stream(*detector_list, name="main_stream", collect=True)

        set_sim_value(flyer.trigger_logic.seq.active, 1)

        yield from bps.kickoff(flyer, wait=True)
        for detector in detector_list:
            yield from bps.kickoff(detector)

        yield from bps.complete(flyer, wait=False, group="complete")
        for detector in detector_list:
            yield from bps.complete(detector, wait=False, group="complete")

        # Manually incremenet the index as if a frame was taken
        for detector in detector_list:
            detector.writer.index += 1

        set_sim_value(flyer.trigger_logic.seq.active, 0)

        done = False
        while not done:
            try:
                yield from bps.wait(group="complete", timeout=0.5)
            except TimeoutError:
                pass
            else:
                done = True
            yield from bps.collect(
                *detector_list,
                return_payload=False,
                name="main_stream",
            )
        yield from bps.wait(group="complete")
        yield from bps.close_run()

        yield from bps.unstage_all(flyer, *detector_list)
        for detector in detector_list:
            assert detector.controller.disarm.called  # type: ignore

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
