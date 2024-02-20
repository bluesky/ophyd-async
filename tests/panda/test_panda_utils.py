from unittest.mock import patch

import pytest
from bluesky import RunEngine

from ophyd_async.core import SignalRW, save_device
from ophyd_async.core.device import DeviceCollector
from ophyd_async.epics.signal import epics_signal_rw
from ophyd_async.panda import PandA
from ophyd_async.panda.utils import phase_sorter


@pytest.fixture
async def sim_panda():
    async with DeviceCollector(sim=True):
        sim_panda = PandA("PANDA")
        sim_panda.phase_1_signal_units: SignalRW = epics_signal_rw(int, "")
    assert sim_panda.name == "sim_panda"
    yield sim_panda


@patch("ophyd_async.core.device_save_loader.save_to_yaml")
async def test_save_panda(mock_save_to_yaml, sim_panda, RE: RunEngine):
    RE(save_device(sim_panda, "path", sorter=phase_sorter))
    mock_save_to_yaml.assert_called_once()
    assert mock_save_to_yaml.call_args[0] == (
        [
            {"phase_1_signal_units": 0},
            {
                "pulse.1.delay": 0.0,
                "pulse.1.width": 0.0,
                "seq.1.table": {},
                "seq.1.active": False,
            },
        ],
        "path",
    )
