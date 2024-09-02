from unittest.mock import patch

import pytest
from bluesky import RunEngine

from ophyd_async.core import DEFAULT_TIMEOUT, DeviceCollector, save_device
from ophyd_async.epics.pvi import fill_pvi_entries
from ophyd_async.epics.signal import epics_signal_rw
from ophyd_async.fastcs.panda import (
    CommonPandaBlocks,
    DataBlock,
    PcompDirectionOptions,
    TimeUnits,
    phase_sorter,
)


@pytest.fixture
async def mock_panda():
    class Panda(CommonPandaBlocks):
        data: DataBlock

        def __init__(self, prefix: str, name: str = ""):
            self._prefix = prefix
            super().__init__(name)

        async def connect(self, mock: bool = False, timeout: float = DEFAULT_TIMEOUT):
            await fill_pvi_entries(
                self, self._prefix + "PVI", timeout=timeout, mock=mock
            )
            await super().connect(mock=mock, timeout=timeout)

    async with DeviceCollector(mock=True):
        mock_panda = Panda("PANDA")
        mock_panda.phase_1_signal_units = epics_signal_rw(int, "")
    assert mock_panda.name == "mock_panda"
    yield mock_panda


@patch("ophyd_async.core._device_save_loader.save_to_yaml")
async def test_save_panda(mock_save_to_yaml, mock_panda, RE: RunEngine):
    RE(save_device(mock_panda, "path", sorter=phase_sorter))
    mock_save_to_yaml.assert_called_once()
    assert mock_save_to_yaml.call_args[0] == (
        [
            {
                "phase_1_signal_units": 0,
                "seq.1.prescale_units": TimeUnits("min"),
                "seq.2.prescale_units": TimeUnits("min"),
            },
            {
                "data.capture": False,
                "data.create_directory": 0,
                "data.flush_period": 0.0,
                "data.hdf_directory": "",
                "data.hdf_file_name": "",
                "data.num_capture": 0,
                "pcap.arm": False,
                "pcomp.1.dir": PcompDirectionOptions.positive,
                "pcomp.1.enable": "ZERO",
                "pcomp.1.pulses": 0,
                "pcomp.1.start": 0,
                "pcomp.1.step": 0,
                "pcomp.1.width": 0,
                "pcomp.2.dir": PcompDirectionOptions.positive,
                "pcomp.2.enable": "ZERO",
                "pcomp.2.pulses": 0,
                "pcomp.2.start": 0,
                "pcomp.2.step": 0,
                "pcomp.2.width": 0,
                "pulse.1.delay": 0.0,
                "pulse.1.width": 0.0,
                "pulse.2.delay": 0.0,
                "pulse.2.width": 0.0,
                "seq.1.active": False,
                "seq.1.table": {},
                "seq.1.repeats": 0,
                "seq.1.prescale": 0.0,
                "seq.1.enable": "ZERO",
                "seq.2.table": {},
                "seq.2.active": False,
                "seq.2.repeats": 0,
                "seq.2.prescale": 0.0,
                "seq.2.enable": "ZERO",
            },
        ],
        "path",
    )
