import bluesky.plan_stubs as bps
import bluesky.plans as bp
import pytest
from bluesky import RunEngine

import ophyd_async.plan_stubs as ops
from ophyd_async.epics import adcore


@pytest.fixture
async def single_trigger_det_with_stats():
    stats = adcore.NDPluginStatsIO("PREFIX:STATS", name="stats")
    det = adcore.SingleTriggerDetector(
        drv=adcore.ADBaseIO("PREFIX:DRV"),
        stats=stats,
        read_uncached=[stats.unique_id],
        name="det",
    )

    # Set non-default values to check they are set back
    # These are using set_mock_value to simulate the backend IOC being setup
    # in a particular way, rather than values being set by the Ophyd signals
    yield det, stats


async def test_single_trigger_det(
    single_trigger_det_with_stats: adcore.SingleTriggerDetector, RE: RunEngine
):
    single_trigger_det, stats = single_trigger_det_with_stats
    names = []
    docs = []
    RE.subscribe(lambda name, _: names.append(name))
    RE.subscribe(lambda _, doc: docs.append(doc))

    def plan():
        yield from ops.ensure_connected(single_trigger_det, mock=True)
        yield from bps.abs_set(single_trigger_det.drv.acquire_time, 0.5)
        yield from bps.abs_set(single_trigger_det.drv.array_counter, 1)
        yield from bps.abs_set(
            single_trigger_det.drv.image_mode, adcore.ImageMode.continuous
        )
        # set_mock_value(stats.unique_id, 3)
        yield from bp.count([single_trigger_det])

    RE(plan())

    drv = single_trigger_det.drv
    assert 1 == await drv.acquire.get_value()
    assert adcore.ImageMode.single == await drv.image_mode.get_value()
    assert True is await drv.wait_for_plugins.get_value()

    assert names == ["start", "descriptor", "event", "stop"]
    _, descriptor, event, _ = docs
    assert descriptor["configuration"]["det"]["data"]["det-drv-acquire_time"] == 0.5
    assert event["data"]["det-drv-array_counter"] == 1
    assert event["data"]["det-stats-unique_id"] == 0
