import pytest

from ophyd_async.core import DeviceCollector, StaticDirectoryProvider
from ophyd_async.panda import HDFPanda


@pytest.fixture
async def sim_hdf_panda(tmp_path):
    directory_provider = StaticDirectoryProvider(str(tmp_path), "test")
    async with DeviceCollector(sim=True):
        sim_hdf_panda = HDFPanda(
            "HDFPANDA:", directory_provider=directory_provider, name="panda"
        )
    yield sim_hdf_panda


async def test_hdf_panda_passes_blocks_to_controller(sim_hdf_panda: HDFPanda):
    assert hasattr(sim_hdf_panda.controller, "pcap")
    assert sim_hdf_panda.controller.pcap is sim_hdf_panda.pcap
