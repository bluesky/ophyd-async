import pytest

from ophyd_async.core.device import DeviceCollector
from ophyd_async.panda import PandA
from ophyd_async.panda.trigger import StaticSeqTableTriggerLogic


@pytest.fixture
async def panda():
    async with DeviceCollector(sim=True):
        sim_panda = PandA("PANDAQSRV:", "sim_panda")

    assert sim_panda.name == "sim_panda"
    yield sim_panda


def test_trigger_logic_has_given_methods(panda: PandA):
    trigger_logic = StaticSeqTableTriggerLogic(panda.seq[1])
    assert hasattr(trigger_logic, "prepare")
    assert hasattr(trigger_logic, "kickoff")
    assert hasattr(trigger_logic, "complete")
    assert hasattr(trigger_logic, "stop")
