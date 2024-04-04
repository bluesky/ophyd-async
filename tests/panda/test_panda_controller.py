"""Test file specifying how we want to interact with the panda controller"""

from unittest.mock import patch

import pytest

from ophyd_async.core import DetectorTrigger, DeviceCollector
from ophyd_async.panda import PandA, PandaPcapController


@pytest.fixture
async def sim_panda():
    async with DeviceCollector(sim=True):
        sim_panda = PandA("PANDACONTROLLER:", "sim_panda")
    yield sim_panda


async def test_panda_controller_fill_blocks_missing_panda_blocks(sim_panda):
    del sim_panda.pcap
    pandaController = PandaPcapController()
    with pytest.raises(RuntimeError) as exc:
        pandaController.fill_blocks(sim_panda)

    assert (
        "pcap block not found in <class 'ophyd_async.panda.panda.PandA'>, "
        "are you sure the panda has been connected?"
    ) in str(exc.value)


async def test_panda_controller_not_filled_blocks(sim_panda):
    pandaController = PandaPcapController()
    with patch("ophyd_async.panda.panda_controller.wait_for_value", return_value=None):
        with pytest.raises(RuntimeError) as exc:
            await pandaController.arm(num=1, trigger=DetectorTrigger.constant_gate)
    assert (
        "pcap block not found in <class 'ophyd_async.panda.panda_controller."
        "PandaPcapController'>, are you sure the panda has been connected?"
    ) in str(exc.value)


async def test_panda_controller_arm_disarm(sim_panda):
    pandaController = PandaPcapController()
    pandaController.fill_blocks(sim_panda)
    with patch("ophyd_async.panda.panda_controller.wait_for_value", return_value=None):
        await pandaController.arm(num=1, trigger=DetectorTrigger.constant_gate)
    await pandaController.disarm()


async def test_panda_controller_wrong_trigger(sim_panda):
    pandaController = PandaPcapController()
    pandaController.fill_blocks(sim_panda)
    with pytest.raises(AssertionError):
        await pandaController.arm(num=1, trigger=DetectorTrigger.internal)
