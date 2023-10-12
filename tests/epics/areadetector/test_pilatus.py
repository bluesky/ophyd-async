from pathlib import Path
from typing import cast

import bluesky.plan_stubs as bps
import pytest
from bluesky import RunEngine
from bluesky.utils import new_uid

from ophyd_async.core import DeviceCollector, StaticDirectoryProvider, set_sim_value
from ophyd_async.epics.areadetector.controllers import PilatusController
from ophyd_async.epics.areadetector.pilatus import HDFStatsPilatus
from ophyd_async.epics.areadetector.writers import HDFWriter

CURRENT_DIRECTORY = Path(__file__).parent


async def make_detector(prefix: str = "") -> HDFStatsPilatus:
    dp = StaticDirectoryProvider(CURRENT_DIRECTORY, f"test-{new_uid()}")

    async with DeviceCollector(sim=True):
        detector = HDFStatsPilatus(prefix, dp)
    return detector


def count_sim(det: HDFStatsPilatus, times: int = 1):
    """Test plan to do the equivalent of bp.count for a sim detector."""

    yield from bps.stage_all(det)
    yield from bps.open_run()
    yield from bps.declare_stream(det, name="primary", collect=False)
    for _ in range(times):
        read_value = yield from bps.rd(cast(HDFStatsPilatus, det.data).hdf.num_captured)
        yield from bps.trigger(det, wait=False, group="wait_for_trigger")

        yield from bps.sleep(0.001)
        set_sim_value(cast(HDFStatsPilatus, det.data).hdf.num_captured, read_value + 1)

        yield from bps.wait(group="wait_for_trigger")
        yield from bps.create()
        yield from bps.read(det)
        yield from bps.save()

    yield from bps.close_run()
    yield from bps.unstage_all(det)


@pytest.fixture
async def single_detector(RE: RunEngine) -> HDFStatsPilatus:
    detector = await make_detector(prefix="TEST")

    set_sim_value(cast(PilatusController, detector.control).driver.array_size_x, 10)
    set_sim_value(cast(PilatusController, detector.control).driver.array_size_y, 20)
    return detector


async def test_pilatus(RE: RunEngine, single_detector: HDFStatsPilatus):
    names = []
    docs = []
    RE.subscribe(lambda name, _: names.append(name))
    RE.subscribe(lambda _, doc: docs.append(doc))

    RE(count_sim(single_detector))
    writer = cast(HDFWriter, single_detector.data)

    assert (
        await writer.hdf.file_path.get_value()
        == writer._directory_provider().directory_path
    )
    assert (await writer.hdf.file_name.get_value()).startswith(
        writer._directory_provider().filename_prefix
    )

    assert names == [
        "start",
        "descriptor",
        "stream_resource",
        "stream_resource",
        "stream_datum",
        "stream_datum",
        "event",
        "stop",
    ]
