import numpy as np
import yaml
from bluesky import RunEngine

from ophyd_async.core import YamlSettingsProvider, init_devices
from ophyd_async.epics.core import epics_signal_rw
from ophyd_async.fastcs.core import fastcs_connector
from ophyd_async.fastcs.panda import (
    CommonPandaBlocks,
    DataBlock,
    PandaTimeUnits,
    SeqTable,
)
from ophyd_async.plan_stubs import (
    apply_panda_settings,
    retrieve_settings,
    store_settings,
)


async def get_mock_panda():
    class Panda(CommonPandaBlocks):
        data: DataBlock

        def __init__(self, uri: str, name: str = ""):
            super().__init__(name=name, connector=fastcs_connector(self, uri))

    async with init_devices(mock=True):
        mock_panda = Panda("PANDA")
        mock_panda.phase_1_signal_units = epics_signal_rw(int, "")
    return mock_panda


async def test_save_load_panda(tmp_path, RE: RunEngine):
    mock_panda1 = await get_mock_panda()
    await mock_panda1.seq[1].table.set(SeqTable.row(repeats=1))
    provider = YamlSettingsProvider(tmp_path)
    RE(store_settings(provider, "panda", mock_panda1))

    def check_equal_with_seq_tables(actual, expected):
        assert actual.model_fields_set == expected.model_fields_set
        for field_name, field_value1 in actual:
            field_value2 = getattr(expected, field_name)
            assert np.array_equal(field_value1, field_value2)

    mock_panda2 = await get_mock_panda()
    check_equal_with_seq_tables(
        (await mock_panda2.seq[1].table.get_value()), SeqTable()
    )

    def load_panda():
        settings = yield from retrieve_settings(provider, "panda", mock_panda2)
        yield from apply_panda_settings(settings)

    RE(load_panda())

    check_equal_with_seq_tables(
        await mock_panda2.seq[1].table.get_value(),
        SeqTable.row(repeats=1),
    )

    # Load the YAML content as a string
    with open(str(tmp_path / "panda.yaml")) as file:
        yaml_content = file.read()

    # Parse the YAML content
    parsed_yaml = yaml.safe_load(yaml_content)

    assert parsed_yaml == {
        "phase_1_signal_units": 0,
        "seq.1.prescale_units": PandaTimeUnits("min"),
        "seq.2.prescale_units": PandaTimeUnits("min"),
        "data.capture": False,
        "data.capture_mode": "FIRST_N",
        "data.create_directory": 0,
        "data.flush_period": 0.0,
        "data.hdf_directory": "",
        "data.hdf_file_name": "",
        "data.num_capture": 0,
        "pcap.arm": False,
        "pcomp.1.dir": "Positive",
        "pcomp.1.enable": "ZERO",
        "pcomp.1.pulses": 0,
        "pcomp.1.start": 0,
        "pcomp.1.step": 0,
        "pcomp.1.width": 0,
        "pcomp.2.dir": "Positive",
        "pcomp.2.enable": "ZERO",
        "pcomp.2.pulses": 0,
        "pcomp.2.start": 0,
        "pcomp.2.step": 0,
        "pcomp.2.width": 0,
        "pulse.1.delay": 0.0,
        "pulse.1.width": 0.0,
        "pulse.1.step": 0.0,
        "pulse.1.pulses": 0,
        "pulse.2.delay": 0.0,
        "pulse.2.width": 0.0,
        "pulse.2.step": 0.0,
        "pulse.2.pulses": 0,
        "seq.1.table": {
            "outa1": [False],
            "outa2": [False],
            "outb1": [False],
            "outb2": [False],
            "outc1": [False],
            "outc2": [False],
            "outd1": [False],
            "outd2": [False],
            "oute1": [False],
            "oute2": [False],
            "outf1": [False],
            "outf2": [False],
            "position": [0],
            "repeats": [1],
            "time1": [0],
            "time2": [0],
            "trigger": ["Immediate"],
        },
        "seq.1.repeats": 0,
        "seq.1.prescale": 0.0,
        "seq.1.enable": "ZERO",
        "seq.2.table": {
            "outa1": [],
            "outa2": [],
            "outb1": [],
            "outb2": [],
            "outc1": [],
            "outc2": [],
            "outd1": [],
            "outd2": [],
            "oute1": [],
            "oute2": [],
            "outf1": [],
            "outf2": [],
            "position": [],
            "repeats": [],
            "time1": [],
            "time2": [],
            "trigger": [],
        },
        "seq.2.repeats": 0,
        "seq.2.prescale": 0.0,
        "seq.2.enable": "ZERO",
    }
