import bluesky.plans as bp
import pytest
from bluesky import RunEngine

from ophyd_async.core import DeviceCollector, set_mock_value
from ophyd_async.epics import adcore


@pytest.fixture
async def single_trigger_det():
    async with DeviceCollector(mock=True):
        stats = adcore.NDPluginStats("PREFIX:STATS")
        det = adcore.SingleTrSingleTriggerDetectoriggerDet(
            drv=adcore.ADBase("PREFIX:DRV"), stats=stats, read_uncached=[stats.unique_id]
        )

    assert det.name == "det"
    assert stats.name == "det-stats"
    # Set non-default values to check they are set back
    # These are using set_mock_value to simulate the backend IOC being setup
    # in a particular way, rather than values being set by the Ophyd signals
    set_mock_value(det.drv.acquire_time, 0.5)
    set_mock_value(det.drv.array_counter, 1)
    set_mock_value(det.drv.image_mode, adcore.ImageMode.continuous)
    set_mock_value(stats.unique_id, 3)
    yield det


async def test_single_trigger_det(single_trigger_det: adcore.SingleTriggerDetector, RE: RunEngine):
    names = []
    docs = []
    RE.subscribe(lambda name, _: names.append(name))
    RE.subscribe(lambda _, doc: docs.append(doc))

    RE(bp.count([single_trigger_det]))

    drv = single_trigger_det.drv
    assert 1 == await drv.acquire.get_value()
    assert adcore.ImageMode.single == await drv.image_mode.get_value()
    assert True is await drv.wait_for_plugins.get_value()

    assert names == ["start", "descriptor", "event", "stop"]
    _, descriptor, event, _ = docs
    assert descriptor["configuration"]["det"]["data"]["det-drv-acquire_time"] == 0.5
    assert event["data"]["det-drv-array_counter"] == 1
    assert event["data"]["det-stats-unique_id"] == 3
