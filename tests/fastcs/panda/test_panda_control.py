"""Test file specifying how we want to interact with the panda controller"""

from unittest.mock import patch

import pytest

from ophyd_async.core import DetectorTrigger, Device, DeviceCollector, TriggerInfo
from ophyd_async.epics.pvi import PviDeviceBackend
from ophyd_async.epics.signal import epics_signal_rw
from ophyd_async.fastcs.panda import CommonPandaBlocks, PandaPcapController


@pytest.fixture
async def mock_panda():
    class Panda(CommonPandaBlocks):
        def __init__(self, prefix: str, name: str = ""):
            self._prefix = prefix
            super().__init__(name, backend=PviDeviceBackend(type(self), prefix + "PVI"))

    async with DeviceCollector(mock=True):
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
                TriggerInfo(number=1, trigger=DetectorTrigger.constant_gate)
            )
            await pandaController.arm()
    assert ("'PcapBlock' object has no attribute 'arm'") in str(exc.value)


async def test_panda_controller_arm_disarm(mock_panda):
    pandaController = PandaPcapController(mock_panda.pcap)
    with patch("ophyd_async.fastcs.panda._control.wait_for_value", return_value=None):
        await pandaController.prepare(
            TriggerInfo(number=1, trigger=DetectorTrigger.constant_gate)
        )
        await pandaController.arm()
        await pandaController.wait_for_idle()
    await pandaController.disarm()


async def test_panda_controller_wrong_trigger():
    pandaController = PandaPcapController(None)
    with pytest.raises(AssertionError):
        await pandaController.prepare(
            TriggerInfo(number=1, trigger=DetectorTrigger.internal)
        )
