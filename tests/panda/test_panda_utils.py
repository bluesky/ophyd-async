from unittest.mock import patch

import pytest
from bluesky import RunEngine

from ophyd_async.core import save_device
from ophyd_async.core.device import DeviceCollector
from ophyd_async.epics.signal import epics_signal_rw
from ophyd_async.panda import PandA
from ophyd_async.panda.utils import phase_sorter


@pytest.fixture
async def sim_panda():
    async with DeviceCollector(sim=True):
        sim_panda = PandA("PANDA:")
        sim_panda.phase_1_signal_units = epics_signal_rw(int, "")
    assert sim_panda.name == "sim_panda"
    yield sim_panda


@patch("ophyd_async.core.device_save_loader.save_to_yaml")
async def test_save_panda(mock_save_to_yaml, sim_panda, RE: RunEngine):
    RE(save_device(sim_panda, "path", sorter=phase_sorter))
    mock_save_to_yaml.assert_called_once()
    assert mock_save_to_yaml.call_args[0] == (
        [
            {
                "phase_1_signal_units": 0,
                "seq.1.prescale_units": "min",
                "seq.2.prescale_units": "min",
            },
            {
                "data.capture": False,
                "data.flush_period": 0.0,
                "data.hdf_directory": "",
                "data.hdf_file_name": "",
                "data.num_capture": 0,
                "pcap.arm": False,
                "pulse.1.delay": 0.0,
                "pulse.1.width": 0.0,
                "pulse.2.delay": 0.0,
                "pulse.2.width": 0.0,
                "seq.1.table": {},
                "seq.1.active": False,
                "seq.1.repeats": 0,
                "seq.1.prescale": 0.0,
                "seq.1.enable": "",
                "seq.2.table": {},
                "seq.2.active": False,
                "seq.2.repeats": 0,
                "seq.2.prescale": 0.0,
                "seq.2.enable": "",
            },
        ],
        "path",
    )
