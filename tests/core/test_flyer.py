import time
from enum import Enum
from typing import AsyncIterator, Dict, Tuple, Union
from unittest.mock import AsyncMock

import bluesky.plan_stubs as bps
import pytest
from bluesky import RunEngine
from bluesky.protocols import Descriptor
from event_model import StreamDatum, StreamResource, compose_stream_resource
from scanspec.core import Frames, Path

from ophyd_async.core import (
    DetectorControl,
    DetectorTrigger,
    DetectorWriter,
    HardwareTriggeredFlyable,
    SameTriggerDetectorGroupLogic,
    ScanSpecFlyable,
    TriggerInfo,
    TriggerLogic,
)


class TriggerState(Enum):
    null = "null"
    preparing = "preparing"
    starting = "starting"
    stopping = "stopping"


class DummyTriggerLogic(TriggerLogic[int]):
    def __init__(self):
        self.state = TriggerState.null

    def trigger_info(self, value: int) -> TriggerInfo:
        return TriggerInfo(
            num=value, trigger=DetectorTrigger.constant_gate, deadtime=0, livetime=10
        )

    async def prepare(self, value: int):
        self.state = TriggerState.preparing
        return value

    async def start(self):
        self.state = TriggerState.starting

    async def stop(self):
        self.state = TriggerState.stopping


class DummyPathTriggerLogic(TriggerLogic[Path]):
    def __init__(self):
        self.state = TriggerState.null

    def trigger_info(self, value: Path) -> TriggerInfo:
        return TriggerInfo(
            num=value, trigger=DetectorTrigger.constant_gate, deadtime=0, livetime=10
        )

    async def prepare(self, value: Path):
        self.state = TriggerState.preparing
        return value

    async def start(self):
        self.state = TriggerState.starting

    async def stop(self):
        self.state = TriggerState.stopping


class DummyWriter(DetectorWriter):
    def __init__(self, name: str, shape: Tuple[int]):
        self._shape = shape
        self._name = name
        self._file: bool = False
        self._last_emitted = 0

    async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        detector_shape = (10, 20)
        return {
            self._name: Descriptor(
                source="sim://some-source",
                shape=self._shape,
                dtype="number",
                external="STREAM:",
            )
        }

    async def wait_for_index(self, index: int) -> None:
        ...

    async def get_indices_written(self) -> int:
        return 1

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[Union[StreamResource, StreamDatum]]:
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
        self._file = False


@pytest.fixture
def detector_group() -> SameTriggerDetectorGroupLogic:
    controllers = [
        AsyncMock(spec=DetectorControl, get_deadtime=lambda num: num),
        AsyncMock(spec=DetectorControl, get_deadtime=lambda num: num),
    ]
    writers = [DummyWriter("testa", (10, 10)), DummyWriter("testb", (10, 10))]
    return SameTriggerDetectorGroupLogic(controllers, writers)


async def test_hardware_triggered_flyable(
    RE: RunEngine, detector_group: SameTriggerDetectorGroupLogic
):
    names = []
    docs = []
    RE.subscribe(lambda name, _: names.append(name))
    RE.subscribe(lambda _, doc: docs.append(doc))

    trigger_logic = DummyTriggerLogic()
    flyer = HardwareTriggeredFlyable(detector_group, trigger_logic, [], name="flyer")

    def flying_plan():
        yield from bps.stage_all(flyer)
        assert trigger_logic.state == TriggerState.stopping

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
                flyer, stream=True, return_payload=False, name="primary"
            )
            yield from bps.sleep(0.001)
        yield from bps.wait(group="complete")
        yield from bps.close_run()

        yield from bps.unstage_all(flyer)
        for controller in detector_group.controllers:
            assert controller.disarm.called  # type: ignore
            assert controller.disarm.call_count == 3  # type: ignore
        assert trigger_logic.state == TriggerState.stopping

    # move the flyer to the correct place, before fly scanning.
    RE(bps.mv(flyer, 1))
    assert trigger_logic.state == TriggerState.preparing
    for controller in detector_group.controllers:
        assert controller.disarm.called  # type: ignore
        assert controller.disarm.call_count == 1  # type: ignore
        assert controller.arm.called  # type: ignore
        assert controller.arm.call_count == 1  # type: ignore

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


async def test_scan_spec_flyable_wont_pause_if_not_flying(
    RE: RunEngine, detector_group: SameTriggerDetectorGroupLogic
):
    trigger_logic = DummyTriggerLogic()
    flyer = ScanSpecFlyable(detector_group, trigger_logic, [], name="flyer")

    with pytest.raises(AssertionError):
        await flyer.pause()

    with pytest.raises(AssertionError):
        await flyer.resume()

    # now check that you can do the first half of a plan, pause it, and it unstages and prepares again.


""" For the moment, this test doesnt work.

This is because you can't add a scanspec Path and an int.
Flyers set a _current_frame to 0 by default, but then expect to be able to add
any generic T value to it from _prepare...
"""
"""   
async def test_scan_spec_flyable_pauses(RE: RunEngine, detector_group: SameTriggerDetectorGroupLogic):
    trigger_logic = DummyPathTriggerLogic()
    
    flyer = ScanSpecFlyable(detector_group, trigger_logic, [], name="flyer")
    
    def kickoff_plan():  
        yield from bps.stage_all(flyer)
        assert trigger_logic.state == TriggerState.stopping

        yield from bps.open_run()
        yield from bps.kickoff(flyer)

    RE(kickoff_plan())
    assert flyer._fly_status, "Kickoff not run"
    await flyer.pause()

    # pausing should have unstaged
    for controller in detector_group.controllers:
        assert controller.disarm.called  # type: ignore
        assert controller.disarm.call_count ==1 # type: ignore

    await flyer.resume()

    def complete_fly():  
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
                flyer, stream=True, return_payload=False, name="primary"
            )
            yield from bps.sleep(0.001)
        yield from bps.wait(group="complete")
        yield from bps.close_run()

        yield from bps.unstage_all(flyer)

    RE(complete_fly())
"""
