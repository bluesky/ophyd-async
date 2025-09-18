"""Test file specifying how we want to interact with the panda controller"""

from unittest.mock import patch

import pytest

from ophyd_async.core import DetectorTrigger, Device, TriggerInfo, init_devices
from ophyd_async.epics.core import epics_signal_rw
from ophyd_async.fastcs.core import fastcs_connector
from ophyd_async.fastcs.panda import CommonPandaBlocks, PandaPcapController


@pytest.fixture
async def mock_panda():
    class Panda(CommonPandaBlocks):
        def __init__(self, uri: str, name: str = ""):
            super().__init__(name=name, connector=fastcs_connector(self, uri))

    async with init_devices(mock=True):
        mock_panda = Panda("PANDACONTROLLER:", name="mock_panda")
        mock_panda.phase_1_signal_units = epics_signal_rw(int, "")
    yield mock_panda


async def test_panda_controller_not_filled_blocks():
    class PcapBlock(Device):
        pass  # Not filled

    pandaController = PandaPcapController(pcap=PcapBlock())
    with patch("ophyd_async.fastcs.panda._control.wait_for_value", return_value=None):
        with pytest.raises(AttributeError) as exc:
            await pandaController.prepare(
                TriggerInfo(number_of_events=1, trigger=DetectorTrigger.CONSTANT_GATE)
            )
            await pandaController.arm()
    assert ("'PcapBlock' object has no attribute 'arm'") in str(exc.value)


async def test_panda_controller_arm_disarm(mock_panda):
    pandaController = PandaPcapController(mock_panda.pcap)
    with patch("ophyd_async.fastcs.panda._control.wait_for_value", return_value=None):
        await pandaController.prepare(
            TriggerInfo(number_of_events=1, trigger=DetectorTrigger.CONSTANT_GATE)
        )
        await pandaController.arm()
        await pandaController.wait_for_idle()
    await pandaController.disarm()


async def test_panda_controller_wrong_trigger():
    pandaController = PandaPcapController(None)
    with pytest.raises(TypeError):
        await pandaController.prepare(
            TriggerInfo(number_of_events=1, trigger=DetectorTrigger.INTERNAL)
        )
