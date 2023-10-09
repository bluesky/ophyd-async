import bluesky.plans as bp
import pytest

from ophyd_async.core import DeviceCollector, set_sim_value
from ophyd_async.epics.areadetector import ImageMode, SingleTriggerDet
from ophyd_async.epics.areadetector.drivers import ADDriver
from ophyd_async.epics.areadetector.writers import NDPluginStats


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


async def test_single_trigger_det(
    single_trigger_det: SingleTriggerDet, RE, doc_holder: DocHolder
):
    RE(bp.count([single_trigger_det]), doc_holder.append)

    drv = single_trigger_det.drv
    assert 1 == await drv.acquire.get_value()
    assert ImageMode.single == await drv.image_mode.get_value()
    assert True is await drv.wait_for_plugins.get_value()

    assert doc_holder.names == ["start", "descriptor", "event", "stop"]
    _, descriptor, event, _ = doc_holder.docs
    assert descriptor["configuration"]["det"]["data"]["det-drv-acquire_time"] == 0.5
    assert (
        descriptor["data_keys"]["det-stats-unique_id"]["source"]
        == "sim://PREFIX:STATSUniqueId_RBV"
    )
    assert event["data"]["det-drv-array_counter"] == 1
    assert event["data"]["det-stats-unique_id"] == 3
