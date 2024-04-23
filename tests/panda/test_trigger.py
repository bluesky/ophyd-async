import pytest

from ophyd_async.core.device import DEFAULT_TIMEOUT, DeviceCollector
from ophyd_async.epics.pvi.pvi import fill_pvi_entries
from ophyd_async.panda import CommonPandaBlocks
from ophyd_async.panda._trigger import StaticSeqTableTriggerLogic


@pytest.fixture
async def panda():
    class Panda(CommonPandaBlocks):
        def __init__(self, prefix: str, name: str = ""):
            self._prefix = prefix
            super().__init__(name)

        async def connect(self, sim: bool = False, timeout: float = DEFAULT_TIMEOUT):
            await fill_pvi_entries(self, self._prefix + "PVI", timeout=timeout, sim=sim)
            await super().connect(sim, timeout)

    async with DeviceCollector(sim=True):
        sim_panda = Panda("PANDAQSRV:", "sim_panda")

    assert sim_panda.name == "sim_panda"
    yield sim_panda


def test_trigger_logic_has_given_methods(panda):
    trigger_logic = StaticSeqTableTriggerLogic(panda.seq[1])
    assert hasattr(trigger_logic, "prepare")
    assert hasattr(trigger_logic, "kickoff")
    assert hasattr(trigger_logic, "complete")
    assert hasattr(trigger_logic, "stop")
