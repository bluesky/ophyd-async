import tempfile
from typing import List, cast

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import bluesky.preprocessors as bpp
import pytest
from bluesky.utils import new_uid

from ophyd_async.core import (
    DeviceCollector,
    DirectoryProvider,
    StandardDetector,
    StaticDirectoryProvider,
    set_sim_value,
)
from ophyd_async.epics.areadetector import FileWriteMode, ImageMode
from ophyd_async.epics.areadetector.controllers import StandardController
from ophyd_async.epics.areadetector.drivers import ADDriver, ADDriverShapeProvider
from ophyd_async.epics.areadetector.writers import HDFWriter, NDFileHDF


class DocHolder:
    def __init__(self):
        self.names = []
        self.docs = []

    def append(self, name, doc):
        self.names.append(name)
        self.docs.append(doc)


@pytest.fixture
def doc_holder():
    return DocHolder()


@pytest.fixture
async def hdf_streamer_dets():
    temporary_directory = tempfile.mkdtemp()
    dp = StaticDirectoryProvider(temporary_directory, f"test-{new_uid()}")
    async with DeviceCollector(sim=True):
        drva = ADDriver(prefix="PREFIX1:DET")
        drvb = ADDriver(prefix="PREFIX2:DET")

        hdfa = NDFileHDF("PREFIX1:HDF")
        hdfb = NDFileHDF("PREFIX2:HDF")

        writera = HDFWriter(hdfa, dp, lambda: "test", ADDriverShapeProvider(drva))
        writerb = HDFWriter(hdfb, dp, lambda: "test", ADDriverShapeProvider(drvb))

        deta = StandardDetector(StandardController(drva), writera, config_sigs=[])
        detb = StandardDetector(StandardController(drvb), writerb, config_sigs=[])

    assert deta.name == "deta"
    assert detb.name == "detb"

    # Simulate backend IOCs being in slightly different states
    for i, det in enumerate((deta, detb)):
        controller = cast(StandardController, det.control)
        writer = cast(HDFWriter, det.data)

        set_sim_value(controller.driver.acquire_time, 0.8 + i)
        set_sim_value(controller.driver.image_mode, ImageMode.continuous)
        set_sim_value(writer.hdf.num_capture, 1000)
        set_sim_value(writer.hdf.num_captured, 1)
        set_sim_value(writer.hdf.full_file_name, f"/tmp/123456/{det.name}.h5")
        set_sim_value(controller.driver.array_size_x, 1024 + i)
        set_sim_value(controller.driver.array_size_y, 768 + i)
    yield deta, detb


async def test_hdf_streamer_dets_step(
    hdf_streamer_dets: List[StandardDetector],
    RE,
    doc_holder: DocHolder,
):
    RE(bp.count(hdf_streamer_dets), doc_holder.append)

    first_controller = cast(StandardController, hdf_streamer_dets[0].control)
    second_writer = cast(HDFWriter, hdf_streamer_dets[1].data)

    drv = first_controller.driver
    assert 1 == await drv.acquire.get_value()
    assert ImageMode.single == await drv.image_mode.get_value()
    assert True is await drv.wait_for_plugins.get_value()

    hdf = second_writer.hdf
    assert True is await hdf.lazy_open.get_value()
    assert True is await hdf.swmr_mode.get_value()
    assert 0 == await hdf.num_capture.get_value()
    assert FileWriteMode.stream == await hdf.file_write_mode.get_value()

    assert doc_holder.names == [
        "start",
        "descriptor",
        "stream_resource",
        "stream_datum",
        "stream_resource",
        "stream_datum",
        "event",
        "stop",
    ]
    _, descriptor, sra, sda, srb, sdb, event, _ = doc_holder.docs
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
