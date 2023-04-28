from typing import cast

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import bluesky.preprocessors as bpp
import pytest
from ophyd.v2.core import DeviceCollector, set_sim_value

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
    set_sim_value(single_trigger_sim.drv.acquire_time, 0.5)
    set_sim_value(single_trigger_sim.drv.array_counter, 1)
    set_sim_value(single_trigger_sim.stats.unique_id, 3)
    yield single_trigger_sim


@pytest.fixture
async def hdf_writing_sim():
    async with DeviceCollector(sim=True):
        hdf_writing_sim = MyHDFWritingSim(prefix="PREFIX")

    assert hdf_writing_sim.name == "hdf_writing_sim"
    set_sim_value(hdf_writing_sim.hdf.num_captured, 1)
    set_sim_value(hdf_writing_sim.hdf.full_file_name, "/tmp/tempfile")
    set_sim_value(hdf_writing_sim.drv.acquire_time, 0.5)
    yield hdf_writing_sim


@pytest.fixture
async def hdf_flyer_sim():
    async with DeviceCollector(sim=True):
        hdf_flyer_sim = MyHDFFlyerSim(prefix="PREFIX")

    assert hdf_flyer_sim.name == "hdf_flyer_sim"
    set_sim_value(hdf_flyer_sim.hdf.num_captured, 1)
    set_sim_value(hdf_flyer_sim.hdf.full_file_name, "/tmp/tempfile")
    set_sim_value(hdf_flyer_sim.drv.acquire_time, 0.5)
    yield hdf_flyer_sim


async def test_single_write_sim(single_trigger_sim: MySingleTriggerSim, RE):
    det = single_trigger_sim
    set_sim_value(det.drv.acquire, 0)
    set_sim_value(det.drv.image_mode, ImageMode.multiple)
    set_sim_value(det.drv.wait_for_plugins, False)

    docs = []

    def append_callback(*args, **kwargs):
        docs.append(args)

    RE(bp.count([det]), append_callback)

    assert (await det.drv.acquire.get_value()) == 1
    assert (await det.drv.image_mode.get_value()) == ImageMode.single
    assert await det.drv.wait_for_plugins.get_value()

    _, (_, descriptor), (_, event), _ = docs

    assert (
        descriptor["configuration"]["single_trigger_sim"]["data"][
            "single_trigger_sim-drv-acquire_time"
        ]
        == 0.5
    )

    assert event["data"]["single_trigger_sim-drv-array_counter"] == 1
    assert event["data"]["single_trigger_sim-stats-unique_id"] == 3


async def test_hdf_writing_sim(hdf_writing_sim: MyHDFWritingSim, RE):
    det = hdf_writing_sim
    set_sim_value(det.drv.acquire, 0)
    set_sim_value(det.drv.image_mode, ImageMode.multiple)
    set_sim_value(det.drv.wait_for_plugins, False)
    set_sim_value(det.hdf.lazy_open, False)
    set_sim_value(det.hdf.file_write_mode, FileWriteMode.single)

    docs = []

    def append_callback(*args, **kwargs):
        docs.append(args)

    RE(bp.count([det]), append_callback)

    assert (await det.drv.acquire.get_value()) == 1
    assert (await det.drv.image_mode.get_value()) == ImageMode.single
    assert await det.drv.wait_for_plugins.get_value()
    assert await det.hdf.lazy_open.get_value()
    assert (await det.hdf.file_write_mode.get_value()) == FileWriteMode.stream

    _, (_, descriptor), (_, resourse), (_, datum), _, _ = docs

    assert (
        descriptor["configuration"]["hdf_writing_sim"]["data"][
            "hdf_writing_sim-drv-acquire_time"
        ]
        == 0.5
    )
    assert resourse["resource_path"] == "/tmp/tempfile"
    assert datum["datum_kwargs"]["point_number"] == 1


async def test_hdf_flyer_sim(hdf_flyer_sim: MyHDFFlyerSim, RE):
    det = hdf_flyer_sim
    set_sim_value(det.drv.num_images, 0)
    set_sim_value(det.drv.acquire, 0)
    set_sim_value(det.drv.image_mode, ImageMode.single)
    set_sim_value(det.drv.wait_for_plugins, False)
    set_sim_value(det.hdf.lazy_open, False)
    set_sim_value(det.hdf.file_write_mode, FileWriteMode.single)

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
        (_, descriptor),
        (_, stream_resource),
        _,
        _,
    ) = docs

    assert (await det.drv.num_images.get_value()) == 5
    assert (await det.drv.acquire.get_value()) == 1
    assert (await det.drv.image_mode.get_value()) == ImageMode.multiple
    assert await det.drv.wait_for_plugins.get_value()
    assert await det.hdf.lazy_open.get_value()
    assert await det.hdf.file_write_mode.get_value() == FileWriteMode.stream

    assert (
        descriptor["configuration"]["hdf_flyer_sim"]["data"][
            "hdf_flyer_sim-drv-acquire_time"
        ]
        == 0.5
    )
    assert stream_resource["resource_path"] == "/tmp/tempfile"
