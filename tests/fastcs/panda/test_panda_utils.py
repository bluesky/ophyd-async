import numpy as np
from bluesky import RunEngine

from ophyd_async.core import DEFAULT_TIMEOUT, DeviceCollector, load_device, save_device
from ophyd_async.epics.pvi import fill_pvi_entries
from ophyd_async.epics.signal import epics_signal_rw
from ophyd_async.fastcs.panda import (
    CommonPandaBlocks,
    DataBlock,
    SeqTable,
    phase_sorter,
)


async def get_mock_panda():
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
    return mock_panda


async def test_save_load_panda(tmp_path, RE: RunEngine):
    mock_panda1 = await get_mock_panda()
    await mock_panda1.seq[1].table.set(SeqTable.row(repeats=1))

    RE(save_device(mock_panda1, str(tmp_path / "panda.yaml"), sorter=phase_sorter))

    def check_equal_with_seq_tables(actual, expected):
        assert actual.model_fields_set == expected.model_fields_set
        for field_name, field_value1 in actual:
            field_value2 = getattr(expected, field_name)
            assert np.array_equal(field_value1, field_value2)

    mock_panda2 = await get_mock_panda()
    check_equal_with_seq_tables(
        (await mock_panda2.seq[1].table.get_value()), SeqTable()
    )
    RE(load_device(mock_panda2, str(tmp_path / "panda.yaml")))

    check_equal_with_seq_tables(
        await mock_panda2.seq[1].table.get_value(),
        SeqTable.row(repeats=1),
    )

    """
    assert mock_save_to_yaml.call_args[0][0][0] == {
        "phase_1_signal_units": 0,
        "seq.1.prescale_units": TimeUnits("min"),
        "seq.2.prescale_units": TimeUnits("min"),
    }
    check_equal_with_seq_tables(mock_save_to_yaml.call_args[0][0][1],
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
                "seq.1.table": SeqTable([]),
                "seq.1.repeats": 0,
                "seq.1.prescale": 0.0,
                "seq.1.enable": "ZERO",
                "seq.2.table": SeqTable([]),
                "seq.2.active": False,
                "seq.2.repeats": 0,
                "seq.2.prescale": 0.0,
                "seq.2.enable": "ZERO",
            },
    )
    assert mock_save_to_yaml.call_args[0][1] == "path"
    """
