import time
from typing import List
from unittest.mock import patch

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import bluesky.preprocessors as bpp
import pytest
from ophyd_async.core.device_collector import DeviceCollector
from ophyd_async.core.signals import set_sim_put_proceeds, set_sim_value

from ophyd_async.devices.areadetector import (
    ADDriver,
    FileWriteMode,
    HDFStreamerDet,
    ImageMode,
    NDFileHDF,
    NDPluginStats,
    SingleTriggerDet,
    TmpDirectoryProvider,
)


@pytest.fixture
async def single_trigger_det():
    async with DeviceCollector(sim=True):
        stats = NDPluginStats("PREFIX:STATS")
        det = SingleTriggerDet(
            drv=ADDriver("PREFIX:DRV"), stats=stats, read_uncached=[stats.unique_id]
        )

    assert det.name == "det"
    assert stats.name == "det-stats"
    # Set non-default values to check they are set back
    # These are using set_sim_value to simulate the backend IOC being setup
    # in a particular way, rather than values being set by the Ophyd signals
    set_sim_value(det.drv.acquire_time, 0.5)
    set_sim_value(det.drv.array_counter, 1)
    set_sim_value(det.drv.image_mode, ImageMode.continuous)
    set_sim_value(stats.unique_id, 3)
    yield det


class DocHolder:
    def __init__(self):
        self.names = []
        self.docs = []

    def append(self, name, doc):
        self.names.append(name)
        self.docs.append(doc)


async def test_single_trigger_det(single_trigger_det: SingleTriggerDet, RE):
    d = DocHolder()
    RE(bp.count([single_trigger_det]), d.append)

    drv = single_trigger_det.drv
    assert 1 == await drv.acquire.get_value()
    assert ImageMode.single == await drv.image_mode.get_value()
    assert True is await drv.wait_for_plugins.get_value()

    assert d.names == ["start", "descriptor", "event", "stop"]
    _, descriptor, event, _ = d.docs
    assert descriptor["configuration"]["det"]["data"]["det-drv-acquire_time"] == 0.5
    assert (
        descriptor["data_keys"]["det-stats-unique_id"]["source"]
        == "sim://PREFIX:STATSUniqueId_RBV"
    )
    assert event["data"]["det-drv-array_counter"] == 1
    assert event["data"]["det-stats-unique_id"] == 3


@pytest.fixture
async def hdf_streamer_dets():
    dp = TmpDirectoryProvider()
    async with DeviceCollector(sim=True):
        deta = HDFStreamerDet(
            drv=ADDriver(prefix="PREFIX1:DET"),
            hdf=NDFileHDF("PREFIX1:HDF"),
            dp=dp,
        )
        detb = HDFStreamerDet(
            drv=ADDriver(prefix="PREFIX1:DET"),
            hdf=NDFileHDF("PREFIX1:HDF"),
            dp=dp,
        )

    assert deta.name == "deta"
    assert detb.name == "detb"
    assert deta.drv.name == "deta-drv"
    assert deta.hdf.name == "deta-hdf"

    # Simulate backend IOCs being in slightly different states
    for i, det in enumerate((deta, detb)):
        set_sim_value(det.drv.acquire_time, 0.8 + i)
        set_sim_value(det.drv.image_mode, ImageMode.continuous)
        set_sim_value(det.hdf.num_capture, 1000)
        set_sim_value(det.hdf.num_captured, 1)
        set_sim_value(det.hdf.full_file_name, f"/tmp/123456/{det.name}.h5")
        set_sim_value(det.drv.array_size_x, 1024 + i)
        set_sim_value(det.drv.array_size_y, 768 + i)
    yield deta, detb


async def test_hdf_streamer_dets_step(hdf_streamer_dets: List[HDFStreamerDet], RE):
    d = DocHolder()
    RE(bp.count(hdf_streamer_dets), d.append)

    drv = hdf_streamer_dets[0].drv
    assert 1 == await drv.acquire.get_value()
    assert ImageMode.single == await drv.image_mode.get_value()
    assert True is await drv.wait_for_plugins.get_value()

    hdf = hdf_streamer_dets[1].hdf
    assert True is await hdf.lazy_open.get_value()
    assert True is await hdf.swmr_mode.get_value()
    assert 0 == await hdf.num_capture.get_value()
    assert FileWriteMode.stream == await hdf.file_write_mode.get_value()

    assert d.names == [
        "start",
        "descriptor",
        "stream_resource",
        "stream_datum",
        "stream_resource",
        "stream_datum",
        "event",
        "stop",
    ]
    _, descriptor, sra, sda, srb, sdb, event, _ = d.docs
    assert descriptor["configuration"]["deta"]["data"]["deta-drv-acquire_time"] == 0.8
    assert descriptor["configuration"]["detb"]["data"]["detb-drv-acquire_time"] == 1.8
    assert descriptor["data_keys"]["deta"]["shape"] == [768, 1024]
    assert descriptor["data_keys"]["detb"]["shape"] == [769, 1025]
    assert sra["resource_path"] == "/tmp/123456/deta.h5"
    assert srb["resource_path"] == "/tmp/123456/detb.h5"
    assert sda["stream_resource"] == sra["uid"]
    assert sdb["stream_resource"] == srb["uid"]
    for sd in (sda, sdb):
        assert sd["event_offset"] == 0
        assert sd["event_count"] == 1
    assert event["data"] == {}


# TODO: write test where they are in the same stream after
#   https://github.com/bluesky/bluesky/issues/1558
async def test_hdf_streamer_dets_fly_different_streams(
    hdf_streamer_dets: List[HDFStreamerDet], RE
):
    d = DocHolder()
    deta, detb = hdf_streamer_dets

    for det in hdf_streamer_dets:
        set_sim_value(det.hdf.num_captured, 5)

    @bpp.stage_decorator(hdf_streamer_dets)
    @bpp.run_decorator()
    def fly_det(num: int):
        # Set the number of images
        yield from bps.mov(deta.drv.num_images, num, detb.drv.num_images, num)
        # Kick them off in parallel and wait to be done
        for det in hdf_streamer_dets:
            yield from bps.kickoff(det, wait=False, group="kickoff")
        yield from bps.wait(group="kickoff")
        # Complete them and repeatedly collect until done
        statuses = []
        for det in hdf_streamer_dets:
            status = yield from bps.complete(det, wait=False, group="complete")
            statuses.append(status)
        while any(status and not status.done for status in statuses):
            yield from bps.sleep(0.1)
            for det in hdf_streamer_dets:
                yield from bps.collect(det, stream=True, return_payload=False)
        yield from bps.wait(group="complete")

    RE(fly_det(5), d.append)

    # TODO: stream_* will come after descriptor soon
    assert d.names == [
        "start",
        "stream_resource",
        "stream_datum",
        "descriptor",
        "stream_resource",
        "stream_datum",
        "descriptor",
        "stop",
    ]

    drv = hdf_streamer_dets[0].drv
    assert 1 == await drv.acquire.get_value()
    assert ImageMode.multiple == await drv.image_mode.get_value()
    assert True is await drv.wait_for_plugins.get_value()

    hdf = hdf_streamer_dets[1].hdf
    assert True is await hdf.lazy_open.get_value()
    assert True is await hdf.swmr_mode.get_value()
    assert 0 == await hdf.num_capture.get_value()
    assert FileWriteMode.stream == await hdf.file_write_mode.get_value()

    _, sra, sda, descriptora, srb, sdb, descriptorb, _ = d.docs

    assert descriptora["configuration"]["deta"]["data"]["deta-drv-acquire_time"] == 0.8
    assert descriptorb["configuration"]["detb"]["data"]["detb-drv-acquire_time"] == 1.8
    assert descriptora["data_keys"]["deta"]["shape"] == [768, 1024]
    assert descriptorb["data_keys"]["detb"]["shape"] == [769, 1025]
    assert sra["resource_path"] == "/tmp/123456/deta.h5"
    assert srb["resource_path"] == "/tmp/123456/detb.h5"
    assert sda["stream_resource"] == sra["uid"]
    assert sdb["stream_resource"] == srb["uid"]
    for sd in (sda, sdb):
        assert sd["event_offset"] == 0
        assert sd["event_count"] == 5


async def test_hdf_streamer_dets_timeout(hdf_streamer_dets: List[HDFStreamerDet]):
    det, _ = hdf_streamer_dets
    await det.stage()
    set_sim_put_proceeds(det.drv.acquire, False)
    await det.kickoff()
    t = time.monotonic()
    with patch("ophyd_async.devices.areadetector.FRAME_TIMEOUT", 0.1):
        with pytest.raises(TimeoutError, match="deta-hdf: writing stalled on frame 1"):
            await det.complete()
    assert 1.0 < time.monotonic() - t < 1.1
