from typing import cast

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import bluesky.preprocessors as bpp
import pytest
from ophyd.v2.core import DeviceCollector
from ophyd.v2.epics import ChannelSim

from ophyd_epics_devices.areadetector import (
    FileWriteMode,
    ImageMode,
    MyHDFFlyerSim,
    MyHDFWritingSim,
    MySingleTriggerSim,
)


@pytest.fixture
async def single_trigger_sim():
    async with DeviceCollector(sim=True):
        single_trigger_sim = MySingleTriggerSim(prefix="PREFIX")

    assert single_trigger_sim.name == "single_trigger_sim"
    acquire_time = cast(ChannelSim, single_trigger_sim.drv.acquire_time.read_channel)
    acquire_time.set_value(0.5)
    array_counter = cast(ChannelSim, single_trigger_sim.drv.array_counter.read_channel)
    array_counter.set_value(1)
    unique_id = cast(ChannelSim, single_trigger_sim.stats.unique_id.read_channel)
    unique_id.set_value(3)
    yield single_trigger_sim


@pytest.fixture
async def hdf_writing_sim():
    async with DeviceCollector(sim=True):
        hdf_writing_sim = MyHDFWritingSim(prefix="PREFIX")

    assert hdf_writing_sim.name == "hdf_writing_sim"
    num_captured = cast(ChannelSim, hdf_writing_sim.hdf.num_captured.read_channel)
    num_captured.set_value(1)
    full_file_name = cast(ChannelSim, hdf_writing_sim.hdf.full_file_name.read_channel)
    full_file_name.set_value("/tmp/tempfile")
    acquire_time = cast(ChannelSim, hdf_writing_sim.drv.acquire_time.read_channel)
    acquire_time.set_value(0.5)
    yield hdf_writing_sim


@pytest.fixture
async def hdf_flyer_sim():
    async with DeviceCollector(sim=True):
        hdf_flyer_sim = MyHDFFlyerSim(prefix="PREFIX")

    assert hdf_flyer_sim.name == "hdf_flyer_sim"
    num_captured = cast(ChannelSim, hdf_flyer_sim.hdf.num_captured.read_channel)
    num_captured.set_value(1)
    full_file_name = cast(ChannelSim, hdf_flyer_sim.hdf.full_file_name.read_channel)
    full_file_name.set_value("/tmp/tempfile")
    acquire_time = cast(ChannelSim, hdf_flyer_sim.drv.acquire_time.read_channel)
    acquire_time.set_value(0.5)
    yield hdf_flyer_sim


async def test_single_write_sim(single_trigger_sim, RE):
    det = single_trigger_sim
    acquire = cast(ChannelSim, det.drv.acquire.write_channel)
    acquire.set_value(0)
    image_mode = cast(ChannelSim, det.drv.image_mode.write_channel)
    image_mode.set_value(ImageMode.multiple)
    wait_for_plugins = cast(ChannelSim, det.drv.wait_for_plugins.write_channel)
    wait_for_plugins.set_value(False)

    docs = []

    def append_callback(*args, **kwargs):
        docs.append(args)

    RE(bp.count([det]), append_callback)

    assert (await acquire.get_value()) == 1
    assert (await image_mode.get_value()) == ImageMode.single
    assert await wait_for_plugins.get_value()

    _, (_, descriptor), (_, event), _ = docs

    assert (
        descriptor["configuration"]["single_trigger_sim"]["data"][
            "single_trigger_sim-drv-acquire_time"
        ]
        == 0.5
    )

    assert event["data"]["single_trigger_sim-drv-array_counter"] == 1
    assert event["data"]["single_trigger_sim-stats-unique_id"] == 3


async def test_hdf_writing_sim(hdf_writing_sim, RE):
    det = hdf_writing_sim
    acquire = cast(ChannelSim, det.drv.acquire.write_channel)
    acquire.set_value(0)
    image_mode = cast(ChannelSim, det.drv.image_mode.write_channel)
    image_mode.set_value(ImageMode.multiple)
    wait_for_plugins = cast(ChannelSim, det.drv.wait_for_plugins.write_channel)
    wait_for_plugins.set_value(False)
    lazy_open = cast(ChannelSim, det.hdf.lazy_open.write_channel)
    lazy_open.set_value(False)
    file_write_mode = cast(ChannelSim, det.hdf.file_write_mode.write_channel)
    file_write_mode.set_value(FileWriteMode.single)

    docs = []

    def append_callback(*args, **kwargs):
        docs.append(args)

    RE(bp.count([det]), append_callback)

    assert (await acquire.get_value()) == 1
    assert (await image_mode.get_value()) == ImageMode.single
    assert await wait_for_plugins.get_value()
    assert await lazy_open.get_value()
    assert (await file_write_mode.get_value()) == FileWriteMode.stream

    _, (_, descriptor), (_, resourse), (_, datum), _, _ = docs

    assert (
        descriptor["configuration"]["hdf_writing_sim"]["data"][
            "hdf_writing_sim-drv-acquire_time"
        ]
        == 0.5
    )
    assert resourse["resource_path"] == "/tmp/tempfile"
    assert datum["datum_kwargs"]["point_number"] == 1


async def test_hdf_flyer_sim(hdf_flyer_sim, RE):
    det = hdf_flyer_sim
    num_images = cast(ChannelSim, det.drv.num_images.write_channel)
    num_images.set_value(0)
    acquire = cast(ChannelSim, det.drv.acquire.write_channel)
    acquire.set_value(0)
    image_mode = cast(ChannelSim, det.drv.image_mode.write_channel)
    image_mode.set_value(ImageMode.single)
    wait_for_plugins = cast(ChannelSim, det.drv.wait_for_plugins.write_channel)
    wait_for_plugins.set_value(False)
    lazy_open = cast(ChannelSim, det.hdf.lazy_open.write_channel)
    lazy_open.set_value(False)
    file_write_mode = cast(ChannelSim, det.hdf.file_write_mode.write_channel)
    file_write_mode.set_value(FileWriteMode.single)

    docs = []

    def append_callback(*args, **kwargs):
        docs.append(args)

    @bpp.run_decorator()
    @bpp.stage_decorator([det])
    def fly_det(num: int):
        yield from bps.mov(det.drv.num_images, num)
        yield from bps.kickoff(det, wait=True)
        status = yield from bps.complete(det, wait=False, group="complete")
        while status and not status.done:
            yield from bps.collect(det, stream=True, return_payload=False)
            yield from bps.sleep(0.1)
        yield from bps.wait(group="complete")
        # One last one
        yield from bps.collect(det, stream=True, return_payload=False)

    RE(fly_det(5), append_callback)

    (
        _,
        (_, stream_resource),
        _,
        (_, descriptor),
        _,
    ) = docs

    assert (await num_images.get_value()) == 5
    assert (await acquire.get_value()) == 1
    assert (await image_mode.get_value()) == ImageMode.multiple
    assert await wait_for_plugins.get_value()
    assert await lazy_open.get_value()
    assert await file_write_mode.get_value() == FileWriteMode.stream

    assert (
        descriptor["configuration"]["hdf_flyer_sim"]["data"][
            "hdf_flyer_sim-drv-acquire_time"
        ]
        == 0.5
    )
    assert stream_resource["resource_path"] == "/tmp/tempfile"
