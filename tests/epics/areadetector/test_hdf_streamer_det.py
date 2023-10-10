import tempfile
from typing import List, cast

from bluesky import RunEngine, Msg
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
from ophyd_async.epics.motion.motor import Motor

@pytest.fixture
async def hdf_streamer_dets():
    temporary_directory = tempfile.mkdtemp()
    dp = StaticDirectoryProvider(temporary_directory, f"test-{new_uid()}")
    async with DeviceCollector(sim=True):
        drva = ADDriver(prefix="PREFIX1:DET")
        drvb = ADDriver(prefix="PREFIX2:DET")

        hdfa = NDFileHDF("PREFIX1:HDF")
        hdfb = NDFileHDF("PREFIX2:HDF")

        writera = HDFWriter(hdfa, dp, lambda: "testa", ADDriverShapeProvider(drva))
        writerb = HDFWriter(hdfb, dp, lambda: "testb", ADDriverShapeProvider(drvb))

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


@pytest.fixture
async def sim_motor():
    async with DeviceCollector(sim=True):
        sim_motor = Motor("BLxxI-MO-TABLE-01:X")
        # Signals connected here

    assert sim_motor.name == "sim_motor"
    set_sim_value(sim_motor.units, "mm")
    set_sim_value(sim_motor.precision, 3)
    set_sim_value(sim_motor.velocity, 1)
    yield sim_motor

async def test_hdf_streamer_dets_step(
    hdf_streamer_dets: List[StandardDetector],
    sim_motor: Motor,
    RE: RunEngine,
):
    names = []
    docs = []
    RE.subscribe(lambda name, _: names.append(name))
    RE.subscribe(lambda _, doc: docs.append(doc))

    def inner_plan(dets: List[StandardDetector]):
        yield Msg("stage", obj=dets[0])
        yield Msg("stage", obj=dets[1])
        yield Msg("open_run")
        yield Msg("declare_stream", name="primary", collect=False)
        yield Msg("trigger", dets[0], group="wait_for_trigger")
        set_sim_value(cast(HDFWriter, dets[0].data).hdf.num_captured, 1)
        yield Msg("trigger", dets[1], group="wait_for_trigger")
        set_sim_value(cast(HDFWriter, dets[1].data).hdf.num_captured, 1)
        yield Msg("wait", group="wait_for_trigger")
        yield Msg("create", name="primary")
        yield Msg("read", obj=dets[0])
        yield Msg("read", obj=dets[1])
        yield Msg("save")
        yield Msg("unstage", obj=dets[0])
        yield Msg("unstage", obj=dets[1])

    RE(inner_plan(hdf_streamer_dets))

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
