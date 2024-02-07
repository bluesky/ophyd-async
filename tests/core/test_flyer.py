import time
from enum import Enum
from typing import AsyncIterator, Dict, Optional, Sequence
from unittest.mock import Mock

import bluesky.plan_stubs as bps
import pytest
from bluesky.protocols import Asset, Descriptor
from bluesky.run_engine import RunEngine
from event_model import ComposeStreamResourceBundle, compose_stream_resource

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorControl,
    DetectorTrigger,
    DetectorWriter,
    HardwareTriggeredFlyable,
    SignalRW,
    SimSignalBackend,
    TriggerInfo,
    TriggerLogic,
)
from ophyd_async.core.detector import StandardDetector


class TriggerState(str, Enum):
    null = "null"
    preparing = "preparing"
    starting = "starting"
    stopping = "stopping"


class DummyTriggerLogic(TriggerLogic[int]):
    def __init__(self):
        self.state = TriggerState.null

    def trigger_info(self, value: int) -> TriggerInfo:
        return TriggerInfo(
            num=value, trigger=DetectorTrigger.constant_gate, deadtime=2, livetime=2
        )

    async def prepare(self, value: int):
        self.state = TriggerState.preparing
        return value

    async def start(self):
        self.state = TriggerState.starting

    async def stop(self):
        self.state = TriggerState.stopping


class DummyWriter(DetectorWriter):
    def __init__(self, name: str, shape: Sequence[int]):
        self.dummy_signal = SignalRW(backend=SimSignalBackend(int, source="test"))
        self._shape = shape
        self._name = name
        self._file: Optional[ComposeStreamResourceBundle] = None
        self._last_emitted = 0

    async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        return {
            self._name: Descriptor(
                source="sim://some-source",
                shape=self._shape,
                dtype="number",
                external="STREAM:",
            )
        }

    async def wait_for_index(
        self, index: int, timeout: Optional[float] = DEFAULT_TIMEOUT
    ) -> None: ...

    async def get_indices_written(self) -> int:
        return 1

    async def collect_stream_docs(self, indices_written: int) -> AsyncIterator[Asset]:
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
                indices = dict(
                    start=self._last_emitted,
                    stop=indices_written,
                )
                self._last_emitted = indices_written
                self._last_flush = time.monotonic()
                yield "stream_datum", self._file.compose_stream_datum(indices)

    async def close(self) -> None:
        self._file = None


@pytest.fixture
async def detector_list(RE: RunEngine) -> tuple[StandardDetector]:
    writers = [DummyWriter("testa", (1, 1)), DummyWriter("testb", (1, 1))]
    await writers[0].dummy_signal.connect(sim=True)

    async def dummy_arm(self=None, trigger=None, num=0, exposure=None):
        return writers[0].dummy_signal.set(1)

    detector_1 = StandardDetector(
        Mock(spec=DetectorControl, get_deadtime=lambda num: num, arm=dummy_arm),
        writers[0],
    )
    detector_2 = StandardDetector(
        Mock(spec=DetectorControl, get_deadtime=lambda num: num, arm=dummy_arm),
        writers[1],
    )

    return (detector_1, detector_2)


async def test_hardware_triggered_flyable(
    RE: RunEngine, detector_list: tuple[StandardDetector]
):
    names = []
    docs = []
    RE.subscribe(lambda name, _: names.append(name))
    RE.subscribe(lambda _, doc: docs.append(doc))

    assert len(detector_list) == 2

    trigger_logic = DummyTriggerLogic()
    flyer = HardwareTriggeredFlyable(trigger_logic, [], name="flyer")

    def flying_plan():
        # move the flyer to the correct place, before fly scanning.
        # Prepare the flyer first to get the trigger info for the detectors
        yield from bps.prepare(flyer, 1, wait=True)

        # prepare detectors second.
        for detector in detector_list:
            yield from bps.prepare(detector, flyer.trigger_info, wait=True)

        assert trigger_logic.state == TriggerState.preparing
        for detector in detector_list:
            detector.controller.disarm.assert_called_once  # type: ignore

        raise Exception("We have prepared")

        yield from bps.stage_all(*detector_list, flyer)
        assert flyer._trigger_logic.state == TriggerState.stopping

        yield from bps.open_run()

        yield from bps.kickoff(flyer)

        yield from bps.complete(flyer, wait=False, group="complete")
        assert trigger_logic.state == TriggerState.starting

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
                stream=True,
                return_payload=False,
                name="primary",
            )
            yield from bps.sleep(0.001)
        yield from bps.wait(group="complete")
        yield from bps.close_run()

        yield from bps.unstage_all(flyer)
        for controller in flyer._detector_group_logic._controllers:
            assert controller.disarm.called  # type: ignore
            assert controller.disarm.call_count == 3  # type: ignore
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
