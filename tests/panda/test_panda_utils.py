from unittest.mock import patch

import pytest
from bluesky import RunEngine

from ophyd_async.core import SignalRW, set_sim_value
from ophyd_async.core.device import DeviceCollector
from ophyd_async.epics.signal import epics_signal_rw
from ophyd_async.panda import PandA, save_panda
from ophyd_async.panda.panda_utils import _get_panda_phases


@pytest.fixture
async def sim_panda():
    async with DeviceCollector(sim=True):
        sim_panda = PandA("PANDA")
        sim_panda.phase_1_signal_units: SignalRW = epics_signal_rw(int, "")
    assert sim_panda.name == "sim_panda"
    yield sim_panda


async def test_get_panda_phases(sim_panda, RE: RunEngine):
    def get_phases(panda):
        phases = yield from _get_panda_phases(panda)
        assert len(phases) == 2
        for key in phases[0].keys():
            assert key[-5:] == "units"
        for key in phases[1].keys():
            assert not key[-5:] == "units"
        return

    set_sim_value(sim_panda.phase_1_signal_units, 1)
    RE(get_phases(sim_panda))


@patch("ophyd_async.panda.panda_utils._get_panda_phases")
@patch("ophyd_async.panda.panda_utils.save_to_yaml")
async def test_save_panda(
    mock_save_to_yaml, mock_get_panda_phases, sim_panda, RE: RunEngine
):
    RE(save_panda(sim_panda, "path"))
    mock_get_panda_phases.assert_called_once()
    mock_save_to_yaml.assert_called_once()
