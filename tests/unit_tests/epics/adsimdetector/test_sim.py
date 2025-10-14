"""Integration tests for a StandardDetector using a ADHDFWriter and SimController."""

import os
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import cast
from unittest.mock import patch

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
import pytest
from bluesky.run_engine import RunEngine
from bluesky.utils import FailedStatus

import ophyd_async.plan_stubs as ops
from ophyd_async.core import (
    AsyncStatus,
    DetectorTrigger,
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
)
from ophyd_async.epics import adcore, adsimdetector
from ophyd_async.testing import assert_emitted, set_mock_value


@pytest.fixture
def test_adsimdetector(ad_standard_det_factory: Callable) -> adsimdetector.SimDetector:
    return ad_standard_det_factory(adsimdetector.SimDetector)


@pytest.fixture
def test_adsimdetector_tiff(
    ad_standard_det_factory: Callable,
) -> adsimdetector.SimDetector:
    return ad_standard_det_factory(adsimdetector.SimDetector, adcore.ADTIFFWriter)


@pytest.fixture
def two_test_adsimdetectors(
    ad_standard_det_factory: Callable,
) -> Sequence[adsimdetector.SimDetector]:
    deta = ad_standard_det_factory(adsimdetector.SimDetector)
    detb = ad_standard_det_factory(adsimdetector.SimDetector, number=2)

    return deta, detb


def count_sim(
    dets: Sequence[adsimdetector.SimDetector],
    times: int = 1,
    trigger_info: TriggerInfo | None = None,
):
    """Test plan to do the equivalent of bp.count for a sim detector."""

    yield from bps.stage_all(*dets)
    yield from bps.open_run()
    if trigger_info:
        for det in dets:
            yield from bps.prepare(det, trigger_info, wait=True)
    for _ in range(times):
        read_values = {}
        for det in dets:
            read_values[det] = yield from bps.rd(det._writer.fileio.num_captured)

        for det in dets:
            yield from bps.trigger(det, wait=False, group="wait_for_trigger")

        yield from bps.sleep(1.0)

        # Assume that the number of images configured is the number of images captured
        for det in dets:
            num_images = yield from bps.rd(det.driver.num_images)
            set_mock_value(
                det._writer.fileio.num_captured,
                read_values[det] + num_images,
            )

        yield from bps.wait(group="wait_for_trigger")
        yield from bps.create()

        for det in dets:
            yield from bps.read(det)

        yield from bps.save()

    yield from bps.close_run()
    yield from bps.unstage_all(*dets)


@pytest.mark.timeout(3.5)
async def test_detector_count_failure(
    test_adsimdetector: adsimdetector.SimDetector,
    RE: RunEngine,
):
    """Preparing a step scan to use more than one event fails.

    Step scans always produce one event.
    """
    trigger_info = TriggerInfo(
        number_of_events=10,
        trigger=DetectorTrigger.INTERNAL,
        exposures_per_event=5,
    )
    try:
        with pytest.raises(FailedStatus) as exc:
            RE(count_sim([test_adsimdetector], times=1, trigger_info=trigger_info))
        assert isinstance(exc.value.__cause__, ValueError)
    finally:
        RE(bps.unstage(test_adsimdetector, wait=True))


@pytest.mark.timeout(7.5)
@pytest.mark.parametrize("exposures_per_event", [1, 5])
async def test_detector_count(
    test_adsimdetector: adsimdetector.SimDetector,
    RE: RunEngine,
    exposures_per_event: int,
):
    docs = defaultdict(list)
    RE.subscribe(lambda name, doc: docs[name].append(doc))
    trigger_info = TriggerInfo(
        number_of_events=1,
        trigger=DetectorTrigger.INTERNAL,
        exposures_per_event=exposures_per_event,
    )
    RE(count_sim([test_adsimdetector], times=5, trigger_info=trigger_info))

    assert_emitted(
        docs,
        start=1,
        descriptor=1,
        stream_resource=1,
        stream_datum=5,
        event=5,
        stop=1,
    )


@pytest.mark.parametrize("exposures_per_event", [1, 5, 15])
async def test_detector_fly(
    test_adsimdetector: adsimdetector.SimDetector,
    RE: RunEngine,
    exposures_per_event: int,
):
    trigger_info = TriggerInfo(
        number_of_events=15,
        trigger=DetectorTrigger.INTERNAL,
        exposures_per_event=exposures_per_event,
    )
    docs = defaultdict(list)
    RE.subscribe(lambda name, doc: docs[name].append(doc))

    def assert_n_stream_datums(
        n: int, start: int | None = None, stop: int | None = None
    ):
        if n == 0:
            assert "stream_datum" not in docs
        else:
            assert len(docs["stream_datum"]) == n
            # check both detectors have the correct start/stop
            seq_nums = docs["stream_datum"][n - 1]["seq_nums"]
            assert seq_nums["start"] == start
            assert seq_nums["stop"] == stop

    @bpp.stage_decorator([test_adsimdetector])
    @bpp.run_decorator()
    def fly_plan():
        yield from bps.prepare(test_adsimdetector, trigger_info, wait=True)
        yield from bps.declare_stream(test_adsimdetector, name="primary")
        yield from bps.kickoff(test_adsimdetector, wait=True)
        yield from bps.complete(test_adsimdetector, wait=False, group="complete_fly")

        # Don't process a full event yet and ensure no stream datum is emitted
        set_mock_value(
            test_adsimdetector.fileio.num_captured, trigger_info.exposures_per_event - 1
        )
        yield from bps.collect(test_adsimdetector)
        assert_n_stream_datums(0)

        # Process a full event and emit a stream datum
        set_mock_value(
            test_adsimdetector.fileio.num_captured, trigger_info.exposures_per_event
        )
        yield from bps.collect(test_adsimdetector)
        assert_n_stream_datums(1, 1, 2)

        if trigger_info.exposures_per_event > 1:
            # Process a full event + 1 exposure and make sure no stream datum is emitted
            set_mock_value(
                test_adsimdetector.fileio.num_captured, trigger_info.exposures_per_event
            )
            yield from bps.collect(test_adsimdetector)
            assert_n_stream_datums(1, 1, 2)

        # Process three full events and emit three stream data
        set_mock_value(
            test_adsimdetector.fileio.num_captured, 3 * trigger_info.exposures_per_event
        )
        yield from bps.collect(test_adsimdetector)
        assert_n_stream_datums(2, 2, 4)

        set_mock_value(
            test_adsimdetector.fileio.num_captured, 5 * trigger_info.exposures_per_event
        )
        yield from bps.collect(test_adsimdetector)
        assert_n_stream_datums(3, 4, 6)

        set_mock_value(
            test_adsimdetector.fileio.num_captured, 7 * trigger_info.exposures_per_event
        )
        yield from bps.collect(test_adsimdetector)
        assert_n_stream_datums(4, 6, 8)

        set_mock_value(
            test_adsimdetector.fileio.num_captured,
            15 * trigger_info.exposures_per_event,
        )
        yield from bps.collect(test_adsimdetector)
        assert_n_stream_datums(5, 8, 16)

        yield from bps.wait(group="complete_fly")

    RE(fly_plan())
    assert_emitted(
        docs, start=1, descriptor=1, stream_resource=1, stream_datum=5, stop=1
    )


async def test_two_detectors_fly_different_rate(
    two_test_adsimdetectors: Sequence[adsimdetector.SimDetector], RE: RunEngine
):
    docs = defaultdict(list)
    RE.subscribe(lambda name, doc: docs[name].append(doc))

    def assert_n_stream_datums(
        n: int, start: int | None = None, stop: int | None = None
    ):
        if n == 0:
            assert "stream_datum" not in docs
        else:
            assert len(docs["stream_datum"]) == n
            # check both detectors have the correct start/stop
            for detector_index in {n - 1, n - 2}:
                seq_nums = docs["stream_datum"][detector_index]["seq_nums"]
                assert seq_nums["start"] == start
                assert seq_nums["stop"] == stop

    @bpp.stage_decorator(two_test_adsimdetectors)
    @bpp.run_decorator()
    def fly_plan():
        for i, det in enumerate(two_test_adsimdetectors):
            yield from bps.prepare(
                det,
                TriggerInfo(
                    number_of_events=15,
                    trigger=DetectorTrigger.INTERNAL,
                    exposures_per_event=i + 1,
                ),
                wait=True,
                group="prepare",
            )
        yield from bps.declare_stream(*two_test_adsimdetectors, name="primary")

        for det in two_test_adsimdetectors:
            yield from bps.kickoff(det, wait=True)
        for det in two_test_adsimdetectors:
            yield from bps.complete(det, wait=False, group="complete_cleanup")

        # det[0] captures 5 frames, but we do not emit a StreamDatum as det[1] has not
        set_mock_value(two_test_adsimdetectors[0].fileio.num_captured, 5)

        yield from bps.collect(*two_test_adsimdetectors)
        assert_n_stream_datums(0)

        # det[0] captures 10 frames, but we do not emit a StreamDatum as det[1] has not
        set_mock_value(two_test_adsimdetectors[0].fileio.num_captured, 10)
        yield from bps.collect(*two_test_adsimdetectors)
        assert_n_stream_datums(0)

        # det[1] has caught up to first 7 frames, emit streamDatum for seq_num {1,4}
        set_mock_value(two_test_adsimdetectors[1].fileio.num_captured, 7)
        yield from bps.collect(*two_test_adsimdetectors)
        assert_n_stream_datums(2, 1, 4)

        # det[1] has caught up to first 14 frames, emit streamDatum for seq_num {4,8}
        set_mock_value(two_test_adsimdetectors[1].fileio.num_captured, 14)
        yield from bps.collect(*two_test_adsimdetectors)
        assert_n_stream_datums(4, 4, 8)

        # Complete both detectors
        for i, det in enumerate(two_test_adsimdetectors):
            set_mock_value(det.fileio.num_captured, 15 * (i + 1))

        # emits stream datum for seq_num {8, 15}
        yield from bps.collect(*two_test_adsimdetectors)
        assert_n_stream_datums(6, 8, 16)

        # Trigger has complete as all expected frames written
        yield from bps.wait("trigger_cleanup")

    RE(fly_plan())
    assert_emitted(
        docs, start=1, descriptor=1, stream_resource=2, stream_datum=6, stop=1
    )


@pytest.mark.timeout(3.5)
async def test_two_detectors_step(
    two_test_adsimdetectors: list[adsimdetector.SimDetector],
    RE: RunEngine,
):
    names = []
    docs = []
    RE.subscribe(lambda name, _: names.append(name))
    RE.subscribe(lambda _, doc: docs.append(doc))
    [
        set_mock_value(det.fileio.file_path_exists, True)
        for det in two_test_adsimdetectors
    ]

    controller_a = two_test_adsimdetectors[0]._controller
    writer_a = two_test_adsimdetectors[0]._writer
    writer_b = two_test_adsimdetectors[1]._writer
    info_a = writer_a._path_provider(device_name=two_test_adsimdetectors[0].name)
    info_b = writer_b._path_provider(device_name=two_test_adsimdetectors[1].name)
    file_name_a = None
    file_name_b = None

    def plan():
        nonlocal file_name_a, file_name_b
        yield from count_sim(two_test_adsimdetectors, times=1)

        drv = controller_a.driver
        assert False is (yield from bps.rd(drv.acquire))
        assert adcore.ADImageMode.MULTIPLE == (yield from bps.rd(drv.image_mode))

        hdfb = cast(adcore.NDFileHDFIO, writer_b.fileio)
        assert True is (yield from bps.rd(hdfb.lazy_open))
        assert True is (yield from bps.rd(hdfb.swmr_mode))
        assert 0 == (yield from bps.rd(hdfb.num_capture))
        assert adcore.ADFileWriteMode.STREAM == (
            yield from bps.rd(hdfb.file_write_mode)
        )

        assert (yield from bps.rd(writer_a.fileio.file_path)) == str(
            info_a.directory_path
        ) + os.sep
        file_name_a = yield from bps.rd(writer_a.fileio.file_name)
        assert file_name_a == info_a.filename

        assert (yield from bps.rd(writer_b.fileio.file_path)) == str(
            info_b.directory_path
        ) + os.sep
        file_name_b = yield from bps.rd(writer_b.fileio.file_name)
        assert file_name_b == info_b.filename

    RE(plan())
    assert names == [
        "start",
        "descriptor",
        "stream_resource",
        "stream_datum",
        "stream_resource",
        "stream_datum",
        "event",
        "stop",
    ]

    _, descriptor, sra, sda, srb, sdb, event, _ = docs
    assert descriptor["configuration"]["test_adsim1"]["data"][
        "test_adsim1-driver-acquire_time"
    ] == pytest.approx(0.8)
    assert descriptor["configuration"]["test_adsim2"]["data"][
        "test_adsim2-driver-acquire_time"
    ] == pytest.approx(1.8)
    assert descriptor["data_keys"]["test_adsim1"]["shape"] == [1, 10, 10]
    assert descriptor["data_keys"]["test_adsim2"]["shape"] == [1, 11, 11]
    assert sda["stream_resource"] == sra["uid"]
    assert sdb["stream_resource"] == srb["uid"]
    assert (
        srb["uri"]
        == "file://localhost/"
        + (info_b.directory_path / info_b.filename).as_posix().lstrip("/")
        + ".h5"
    )
    assert (
        sra["uri"]
        == "file://localhost/"
        + (info_a.directory_path / info_a.filename).as_posix().lstrip("/")
        + ".h5"
    )

    assert event["data"] == {}


@pytest.mark.timeout(5.5)
@pytest.mark.parametrize(
    "writer_cls", [adcore.ADHDFWriter, adcore.ADTIFFWriter, adcore.ADJPEGWriter]
)
async def test_detector_writes_to_file(
    RE: RunEngine,
    ad_standard_det_factory: Callable,
    writer_cls: type[adcore.ADWriter],
    tmp_path: Path,
):
    test_adsimdetector: adsimdetector.SimDetector = ad_standard_det_factory(
        adsimdetector.SimDetector, writer_cls
    )

    names = []
    docs = []
    RE.subscribe(lambda name, _: names.append(name))
    RE.subscribe(lambda _, doc: docs.append(doc))
    set_mock_value(
        test_adsimdetector.fileio.file_path_exists,
        True,
    )

    RE(count_sim([test_adsimdetector], times=3))

    assert (
        await test_adsimdetector.fileio.file_path.get_value() == str(tmp_path) + os.sep
    )

    descriptor_index = names.index("descriptor")

    assert docs[descriptor_index].get("data_keys").get(test_adsimdetector.name).get(
        "shape"
    ) == [
        1,
        10,
        10,
    ]
    assert names == [
        "start",
        "descriptor",
        "stream_resource",
        "stream_datum",
        "event",
        "stream_datum",
        "event",
        "stream_datum",
        "event",
        "stop",
    ]


async def test_read_and_describe_detector(
    test_adsimdetector: adsimdetector.SimDetector,
):
    describe = await test_adsimdetector.describe_configuration()
    read = await test_adsimdetector.read_configuration()
    assert describe == {
        "test_adsim1-driver-acquire_time": {
            "source": "mock+ca://SIM1:cam1:AcquireTime_RBV",
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
        },
        "test_adsim1-driver-acquire_period": {
            "source": "mock+ca://SIM1:cam1:AcquirePeriod_RBV",
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
        },
    }
    assert read == {
        "test_adsim1-driver-acquire_time": {
            "value": 0.8,
            "timestamp": pytest.approx(time.time(), rel=1e-2),
            "alarm_severity": 0,
        },
        "test_adsim1-driver-acquire_period": {
            "value": 1.0,
            "timestamp": pytest.approx(time.time(), rel=1e-2),
            "alarm_severity": 0,
        },
    }


async def test_read_returns_nothing(test_adsimdetector: adsimdetector.SimDetector):
    assert await test_adsimdetector.read() == {}


async def test_trigger_logic():
    """I want this test to check that when StandardDetector.trigger is called:

    1. the detector.controller is armed, and that starts the acquisition so that,
    2. The detector.writer.hdf.num_captured is 1

    Probably the best thing to do here is mock the detector.controller.driver and
    detector.writer.hdf. Then, mock out set_and_wait_for_value in the SimController
    so that, as well as setting detector.controller.driver.acquire to True, it sets
    detector.writer.hdf.num_captured to 1, using set_mock_value
    """
    ...


@pytest.mark.parametrize(
    "driver_name, error_output",
    [
        ("", "config signal must be named before it is passed to the detector"),
        (
            "some-name",
            (
                "config signal some-name-acquire_time must be connected before it is "
                "passed to the detector"
            ),
        ),
    ],
)
def test_detector_with_unnamed_or_disconnected_config_sigs(
    RE,
    static_filename_provider: StaticFilenameProvider,
    tmp_path: Path,
    driver_name,
    error_output,
):
    dp = StaticPathProvider(static_filename_provider, tmp_path)

    some_other_driver = adsimdetector.SimDriverIO("TEST", name=driver_name)

    det = adsimdetector.SimDetector(
        "FOO:",
        dp,
        name="foo",
    )

    det._config_sigs = [some_other_driver.acquire_time, det.driver.acquire]

    def my_plan():
        yield from ops.ensure_connected(det, mock=True)
        assert det.driver.acquire.name == "foo-driver-acquire"
        assert some_other_driver.acquire_time.name == (
            driver_name + "-acquire_time" if driver_name else ""
        )

        yield from count_sim([det], times=1)

    with pytest.raises(Exception) as exc:
        RE(my_plan())

    assert isinstance(exc.value.args[0], AsyncStatus)
    assert str(exc.value.args[0].exception()) == error_output

    # Need to unstage to properly kill tasks
    RE(bps.unstage(det, wait=True))


async def test_ad_sim_controller(test_adsimdetector: adsimdetector.SimDetector):
    ad = test_adsimdetector._controller
    with patch("ophyd_async.core._signal.wait_for_value", return_value=None):
        await ad.prepare(
            TriggerInfo(number_of_events=1, trigger=DetectorTrigger.INTERNAL)
        )
        await ad.arm()
        await ad.wait_for_idle()

    driver = ad.driver
    assert await driver.num_images.get_value() == 1
    assert await driver.image_mode.get_value() == adcore.ADImageMode.MULTIPLE
    assert await driver.acquire.get_value() is True

    await ad.disarm()

    assert await driver.acquire.get_value() is False
