import time
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from unittest.mock import Mock

import bluesky.plan_stubs as bps
import pytest
from bluesky.protocols import StreamAsset
from bluesky.run_engine import RunEngine
from event_model import ComposeStreamResourceBundle, DataKey, compose_stream_resource

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncReadable,
    AsyncStatus,
    DetectorController,
    DetectorWriter,
    DeviceCollector,
    FlyerController,
    SignalR,
    StandardDetector,
    StandardFlyer,
    WatchableAsyncStatus,
    WatcherUpdate,
    observe_value,
    set_mock_value,
)
from ophyd_async.epics.pvi import fill_pvi_entries
from ophyd_async.epics.signal import epics_signal_rw
from ophyd_async.fastcs.panda import (
    CommonPandaBlocks,
    StaticPcompTriggerLogic,
    StaticSeqTableTriggerLogic,
)
from ophyd_async.plan_stubs import (
    prepare_static_seq_table_flyer_and_detectors_with_same_trigger,
    time_resolved_fly_and_collect_with_static_seq_table,
)


class DummyWriter(DetectorWriter):
    def __init__(self, name: str, shape: Sequence[int]):
        self.dummy_signal = epics_signal_rw(int, "pva://read_pv")
        self._shape = shape
        self._name = name
        self._file: ComposeStreamResourceBundle | None = None
        self._last_emitted = 0
        self.index = 0
        self.observe_indices_written_timeout_log = []

    async def open(self, multiplier: int = 1) -> dict[str, DataKey]:
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
        self.observe_indices_written_timeout_log.append(timeout)
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
                    uri="file://",
                    data_key=self._name,
                    parameters={
                        "path": "",
                        "swmr": False,
                        "multiplier": 1,
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

    def increment_index(self) -> None:
        self.index += 1


class MockDetector(StandardDetector):
    def __init__(
        self,
        controller: DetectorController,
        writer: DetectorWriter,
        config_sigs: Sequence[AsyncReadable] = [],
        name: str = "",
    ) -> None:
        super().__init__(controller, writer, config_sigs, name)

    @WatchableAsyncStatus.wrap
    async def complete(self):
        assert self._trigger_info
        assert self._fly_start
        self.writer.increment_index()
        async for index in self.writer.observe_indices_written(
            self._trigger_info.frame_timeout
            or (
                DEFAULT_TIMEOUT
                + self._trigger_info.livetime
                + self._trigger_info.deadtime
            )
        ):
            yield WatcherUpdate(
                name=self.name,
                current=index,
                initial=self._initial_frame,
                target=self._trigger_info.number_of_triggers,
                unit="",
                precision=0,
                time_elapsed=time.monotonic() - self._fly_start,
            )
            if (
                isinstance(self._trigger_info.number_of_triggers, int)
                and index >= self._trigger_info.number_of_triggers
            ):
                break


@pytest.fixture
async def detectors(RE: RunEngine) -> tuple[MockDetector, MockDetector]:
    writers = [DummyWriter("testa", (1, 1)), DummyWriter("testb", (1, 1))]
    await writers[0].dummy_signal.connect(mock=True)
    await writers[1].dummy_signal.connect(mock=True)

    def dummy_arm_1(self=None):
        return writers[0].dummy_signal.set(1)

    def dummy_arm_2(self=None):
        return writers[1].dummy_signal.set(1)

    detector_1 = MockDetector(
        Mock(spec=DetectorController, get_deadtime=lambda num: num, arm=dummy_arm_1),
        writers[0],
        name="detector_1",
    )
    detector_2 = MockDetector(
        Mock(spec=DetectorController, get_deadtime=lambda num: num, arm=dummy_arm_2),
        writers[1],
        name="detector_2",
    )
    return (detector_1, detector_2)


@pytest.fixture
async def mock_panda():
    class Panda(CommonPandaBlocks):
        def __init__(self, prefix: str, name: str = ""):
            self._prefix = prefix
            super().__init__(name)

        async def connect(self, mock: bool = False, timeout: float = DEFAULT_TIMEOUT):
            await fill_pvi_entries(
                self, self._prefix + "PVI", timeout=timeout, mock=mock
            )
            await super().connect(mock, timeout)

    async with DeviceCollector(mock=True):
        mock_panda = Panda("PANDAQSRV:", "mock_panda")

    assert mock_panda.name == "mock_panda"
    yield mock_panda


class MockFlyer(StandardFlyer):
    def __init__(
        self,
        trigger_logic: FlyerController,
        configuration_signals: Sequence[SignalR] = ...,
        name: str = "",
    ):
        super().__init__(trigger_logic, name)

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        set_mock_value(self.trigger_logic.seq.active, 1)
        await super().kickoff()

    @AsyncStatus.wrap
    async def complete(self) -> None:
        set_mock_value(self.trigger_logic.seq.active, 0)
        await self._trigger_logic.complete()


@pytest.fixture
async def seq_flyer(mock_panda):
    # Make flyer
    trigger_logic = StaticSeqTableTriggerLogic(mock_panda.seq[1])
    flyer = MockFlyer(trigger_logic, name="flyer")

    return flyer


@pytest.fixture
async def pcomp_flyer(mock_panda):
    # Make flyer
    trigger_logic = StaticPcompTriggerLogic(mock_panda.pcomp[1])
    flyer = MockFlyer(trigger_logic, name="flyer")

    return flyer


async def test_hardware_triggered_flyable_with_static_seq_table_logic(
    RE: RunEngine,
    detectors: tuple[StandardDetector],
    mock_panda,
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
    detector_list = list(detectors)

    def append_and_print(name, doc):
        names.append(name)
        docs.append(doc)

    RE.subscribe(append_and_print)

    number_of_frames = 1
    exposure = 1
    shutter_time = 0.004

    trigger_logic = StaticSeqTableTriggerLogic(mock_panda.seq[1])
    flyer = StandardFlyer(trigger_logic, name="flyer")

    def flying_plan():
        yield from bps.stage_all(*detector_list, flyer)

        yield from prepare_static_seq_table_flyer_and_detectors_with_same_trigger(
            flyer,
            detector_list,
            number_of_frames=number_of_frames,
            exposure=exposure,
            shutter_time=shutter_time,
        )

        for detector in detector_list:
            detector.controller.disarm.assert_called_once()  # type: ignore

        yield from bps.open_run()
        yield from bps.declare_stream(*detector_list, name="main_stream", collect=True)

        set_mock_value(flyer.trigger_logic.seq.active, 1)

        yield from bps.kickoff(flyer, wait=True)
        for detector in detector_list:
            yield from bps.kickoff(detector)

        yield from bps.complete(flyer, wait=False, group="complete")
        for detector in detector_list:
            yield from bps.complete(detector, wait=False, group="complete")

        # Manually incremenet the index as if a frame was taken
        for detector in detector_list:
            detector.writer.increment_index()

        set_mock_value(flyer.trigger_logic.seq.active, 0)

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


async def test_time_resolved_fly_and_collect_with_static_seq_table(
    RE: RunEngine,
    detectors: tuple[StandardDetector],
    seq_flyer,
):
    names = []
    docs = []
    detector_list = list(detectors)

    def append_and_print(name, doc):
        names.append(name)
        docs.append(doc)

    RE.subscribe(append_and_print)

    # Trigger parameters
    number_of_frames = 1
    exposure = 1
    shutter_time = 0.004

    def fly():
        yield from bps.stage_all(*detector_list, seq_flyer)
        yield from bps.open_run()
        yield from time_resolved_fly_and_collect_with_static_seq_table(
            stream_name="stream1",
            flyer=seq_flyer,
            detectors=detector_list,
            number_of_frames=number_of_frames,
            exposure=exposure,
            shutter_time=shutter_time,
        )
        yield from bps.close_run()
        yield from bps.unstage_all(seq_flyer, *detector_list)

    # fly scan
    RE(fly())

    assert names == [
        "start",
        "descriptor",
        "stream_resource",
        "stream_datum",
        "stream_resource",
        "stream_datum",
        "stop",
    ]


@pytest.mark.parametrize("detector_list", [[], None])
async def test_at_least_one_detector_in_fly_plan(
    RE: RunEngine,
    seq_flyer,
    detector_list,
):
    # Trigger parameters
    number_of_frames = 1
    exposure = 1
    shutter_time = 0.004

    assert not detector_list

    def fly():
        yield from time_resolved_fly_and_collect_with_static_seq_table(
            stream_name="stream1",
            flyer=seq_flyer,
            detectors=detector_list,
            number_of_frames=number_of_frames,
            exposure=exposure,
            shutter_time=shutter_time,
        )

    with pytest.raises(ValueError) as exc:
        RE(fly())
        assert str(exc) == "No detectors provided. There must be at least one."


@pytest.mark.parametrize("timeout_setting,expected_timeout", [(None, 12), (5.0, 5.0)])
async def test_trigger_sets_or_defaults_timeout(
    RE: RunEngine,
    seq_flyer: StandardFlyer,
    detectors: tuple[StandardDetector, ...],
    timeout_setting: float | None,
    expected_timeout: float,
):
    detector_list = list(detectors)

    # Trigger parameters
    number_of_frames = 1
    exposure = 1
    shutter_time = 0.004

    def fly():
        yield from bps.stage_all(*detector_list, seq_flyer)
        yield from bps.open_run()
        yield from time_resolved_fly_and_collect_with_static_seq_table(
            stream_name="stream1",
            flyer=seq_flyer,
            detectors=detector_list,
            number_of_frames=number_of_frames,
            exposure=exposure,
            shutter_time=shutter_time,
            frame_timeout=timeout_setting,
        )
        yield from bps.close_run()
        yield from bps.unstage_all(seq_flyer, *detector_list)

    RE(fly())

    for detector in detectors:
        assert detector.writer.observe_indices_written_timeout_log == [expected_timeout]
