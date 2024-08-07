"""Integration tests for a StandardDetector using a ADHDFWriter and SimController."""

import time
from collections import defaultdict
from pathlib import Path
from typing import List, cast

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
import pytest
from bluesky import RunEngine
from bluesky.utils import new_uid

from ophyd_async.core import (
    AsyncStatus,
    DetectorTrigger,
    DeviceCollector,
    StandardDetector,
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
    assert_emitted,
    callback_on_mock_put,
    set_mock_value,
)
from ophyd_async.epics import adcore, adsimdetector


async def make_detector(prefix: str, name: str, tmp_path: Path):
    fp = StaticFilenameProvider(f"test-{new_uid()}")
    dp = StaticPathProvider(fp, tmp_path)

    async with DeviceCollector(mock=True):
        drv = adcore.ADBaseIO(f"{prefix}DRV:", name="drv")
        hdf = adcore.NDFileHDFIO(f"{prefix}HDF:")
        det = adsimdetector.SimDetector(
            drv, hdf, dp, config_sigs=[drv.acquire_time, drv.acquire], name=name
        )

    def _set_full_file_name(val, *args, **kwargs):
        set_mock_value(hdf.full_file_name, str(tmp_path / val))

    callback_on_mock_put(hdf.file_name, _set_full_file_name)

    return det


def count_sim(dets: List[StandardDetector], times: int = 1):
    """Test plan to do the equivalent of bp.count for a sim detector."""

    yield from bps.stage_all(*dets)
    yield from bps.open_run()
    for _ in range(times):
        read_values = {}
        for det in dets:
            read_values[det] = yield from bps.rd(
                cast(adcore.ADHDFWriter, det.writer).hdf.num_captured
            )

        for det in dets:
            yield from bps.trigger(det, wait=False, group="wait_for_trigger")

        yield from bps.sleep(0.1)
        [
            set_mock_value(
                cast(adcore.ADHDFWriter, det.writer).hdf.num_captured,
                read_values[det] + 1,
            )
            for det in dets
        ]

        yield from bps.wait(group="wait_for_trigger")
        yield from bps.create()

        for det in dets:
            yield from bps.read(det)

        yield from bps.save()

    yield from bps.close_run()
    yield from bps.unstage_all(*dets)


@pytest.fixture
async def single_detector(RE: RunEngine, tmp_path: Path) -> StandardDetector:
    detector = await make_detector(prefix="TEST:", name="test", tmp_path=tmp_path)

    set_mock_value(detector._controller.driver.array_size_x, 10)
    set_mock_value(detector._controller.driver.array_size_y, 20)
    return detector


@pytest.fixture
async def two_detectors(tmp_path: Path):
    deta = await make_detector(prefix="PREFIX1:", name="testa", tmp_path=tmp_path)
    detb = await make_detector(prefix="PREFIX2:", name="testb", tmp_path=tmp_path)

    # Simulate backend IOCs being in slightly different states
    for i, det in enumerate((deta, detb)):
        # accessing the hidden objects just for neat typing
        controller = det._controller
        writer = det._writer

        set_mock_value(controller.driver.acquire_time, 0.8 + i)
        set_mock_value(controller.driver.image_mode, adcore.ImageMode.continuous)
        set_mock_value(writer.hdf.num_capture, 1000)
        set_mock_value(writer.hdf.num_captured, 0)
        set_mock_value(writer.hdf.file_path_exists, True)
        set_mock_value(controller.driver.array_size_x, 1024 + i)
        set_mock_value(controller.driver.array_size_y, 768 + i)
    yield deta, detb


async def test_two_detectors_fly_different_rate(
    two_detectors: List[adsimdetector.SimDetector], RE: RunEngine
):
    trigger_info = TriggerInfo(
        number=15,
        trigger=DetectorTrigger.internal,
        deadtime=None,
        livetime=None,
        frame_timeout=None,
    )
    docs = defaultdict(list)

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

    @bpp.stage_decorator(two_detectors)
    @bpp.run_decorator()
    def fly_plan():
        for det in two_detectors:
            yield from bps.prepare(det, trigger_info, wait=True, group="prepare")
        yield from bps.declare_stream(*two_detectors, name="primary")

        for det in two_detectors:
            yield from bps.trigger(det, wait=False, group="trigger_cleanup")

        # det[0] captures 5 frames, but we do not emit a StreamDatum as det[1] has not
        set_mock_value(two_detectors[0].hdf.num_captured, 5)

        yield from bps.collect(*two_detectors)
        assert_n_stream_datums(0)

        # det[0] captures 10 frames, but we do not emit a StreamDatum as det[1] has not
        set_mock_value(two_detectors[0].hdf.num_captured, 10)
        yield from bps.collect(*two_detectors)
        assert_n_stream_datums(0)

        # det[1] has caught up to first 7 frames, emit streamDatum for seq_num {1,7}
        set_mock_value(two_detectors[1].hdf.num_captured, 7)
        yield from bps.collect(*two_detectors)
        assert_n_stream_datums(2, 1, 8)

        for det in two_detectors:
            set_mock_value(det.hdf.num_captured, 15)

        # emits stream datum for seq_num {8, 15}
        yield from bps.collect(*two_detectors)
        assert_n_stream_datums(4, 8, 16)

        # Trigger has complete as all expected frames written
        yield from bps.wait("trigger_cleanup")

    RE(fly_plan(), lambda name, doc: docs[name].append(doc))
    assert_emitted(
        docs, start=1, descriptor=1, stream_resource=2, stream_datum=4, stop=1
    )


async def test_two_detectors_step(
    two_detectors: List[StandardDetector],
    RE: RunEngine,
):
    names = []
    docs = []
    RE.subscribe(lambda name, _: names.append(name))
    RE.subscribe(lambda _, doc: docs.append(doc))
    [
        set_mock_value(cast(adcore.ADHDFWriter, det._writer).hdf.file_path_exists, True)
        for det in two_detectors
    ]

    RE(count_sim(two_detectors, times=1))

    controller_a = cast(adsimdetector.SimController, two_detectors[0].controller)
    writer_a = cast(adcore.ADHDFWriter, two_detectors[0].writer)
    writer_b = cast(adcore.ADHDFWriter, two_detectors[1].writer)

    drv = controller_a.driver
    assert 1 == await drv.acquire.get_value()
    assert adcore.ImageMode.multiple == await drv.image_mode.get_value()

    hdfb = writer_b.hdf
    assert True is await hdfb.lazy_open.get_value()
    assert True is await hdfb.swmr_mode.get_value()
    assert 0 == await hdfb.num_capture.get_value()
    assert adcore.FileWriteMode.stream == await hdfb.file_write_mode.get_value()

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
    info_a = writer_a._path_provider(device_name=writer_a.hdf.name)
    info_b = writer_b._path_provider(device_name=writer_b.hdf.name)

    assert await writer_a.hdf.file_path.get_value() == str(info_a.directory_path)
    file_name_a = await writer_a.hdf.file_name.get_value()
    assert file_name_a == info_a.filename

    assert await writer_b.hdf.file_path.get_value() == str(info_b.directory_path)
    file_name_b = await writer_b.hdf.file_name.get_value()
    assert file_name_b == info_b.filename

    _, descriptor, sra, sda, srb, sdb, event, _ = docs
    assert descriptor["configuration"]["testa"]["data"]["testa-drv-acquire_time"] == 0.8
    assert descriptor["configuration"]["testb"]["data"]["testb-drv-acquire_time"] == 1.8
    assert descriptor["data_keys"]["testa"]["shape"] == (768, 1024)
    assert descriptor["data_keys"]["testb"]["shape"] == (769, 1025)
    assert sda["stream_resource"] == sra["uid"]
    assert sdb["stream_resource"] == srb["uid"]
    assert srb["uri"] == str("file://localhost") + str(
        info_b.directory_path / file_name_b
    )
    assert sra["uri"] == str("file://localhost") + str(
        info_a.directory_path / file_name_a
    )

    assert event["data"] == {}


async def test_detector_writes_to_file(
    RE: RunEngine, single_detector: StandardDetector, tmp_path: Path
):
    names = []
    docs = []
    RE.subscribe(lambda name, _: names.append(name))
    RE.subscribe(lambda _, doc: docs.append(doc))
    set_mock_value(
        cast(adcore.ADHDFWriter, single_detector._writer).hdf.file_path_exists, True
    )

    RE(count_sim([single_detector], times=3))

    assert await cast(
        adcore.ADHDFWriter, single_detector.writer
    ).hdf.file_path.get_value() == str(tmp_path)

    descriptor_index = names.index("descriptor")

    assert docs[descriptor_index].get("data_keys").get("test").get("shape") == (20, 10)
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


async def test_read_and_describe_detector(single_detector: StandardDetector):
    describe = await single_detector.describe_configuration()
    read = await single_detector.read_configuration()
    assert describe == {
        "test-drv-acquire_time": {
            "source": "mock+ca://TEST:DRV:AcquireTime_RBV",
            "dtype": "number",
            "dtype_numpy": "<f8",
            "shape": [],
        },
        "test-drv-acquire": {
            "source": "mock+ca://TEST:DRV:Acquire_RBV",
            "dtype": "boolean",
            "dtype_numpy": "|b1",
            "shape": [],
        },
    }
    assert read == {
        "test-drv-acquire_time": {
            "value": 0.0,
            "timestamp": pytest.approx(time.monotonic(), rel=1e-2),
            "alarm_severity": 0,
        },
        "test-drv-acquire": {
            "value": False,
            "timestamp": pytest.approx(time.monotonic(), rel=1e-2),
            "alarm_severity": 0,
        },
    }


async def test_read_returns_nothing(single_detector: StandardDetector):
    assert await single_detector.read() == {}


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


async def test_detector_with_unnamed_or_disconnected_config_sigs(
    RE, static_filename_provider: StaticFilenameProvider, tmp_path: Path
):
    dp = StaticPathProvider(static_filename_provider, tmp_path)
    drv = adcore.ADBaseIO("FOO:DRV:")

    some_other_driver = adcore.ADBaseIO("TEST")

    async with DeviceCollector(mock=True):
        hdf = adcore.NDFileHDFIO("FOO:HDF:")
        det = adsimdetector.SimDetector(
            drv,
            hdf,
            dp,
            config_sigs=[some_other_driver.acquire_time, drv.acquire],
            name="foo",
        )

    with pytest.raises(Exception) as exc:
        RE(count_sim([det], times=1))

    assert isinstance(exc.value.args[0], AsyncStatus)
    assert (
        str(exc.value.args[0].exception())
        == "config signal must be named before it is passed to the detector"
    )

    some_other_driver.set_name("some-name")

    with pytest.raises(Exception) as exc:
        RE(count_sim([det], times=1))

    assert isinstance(exc.value.args[0], AsyncStatus)
    assert (
        str(exc.value.args[0].exception())
        == "config signal some-name-acquire_time must be connected before it is "
        + "passed to the detector"
    )
