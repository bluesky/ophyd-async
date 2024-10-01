import asyncio

import numpy as np
import pytest
from pydantic import ValidationError

from ophyd_async.core import DEFAULT_TIMEOUT, DeviceCollector, set_mock_value
from ophyd_async.epics.pvi import fill_pvi_entries
from ophyd_async.fastcs.panda import (
    CommonPandaBlocks,
    PcompInfo,
    SeqTable,
    SeqTableInfo,
    StaticPcompTriggerLogic,
    StaticSeqTableTriggerLogic,
)
from ophyd_async.fastcs.panda._table import SeqTrigger


@pytest.fixture
async def mock_panda():
    class Panda(CommonPandaBlocks):
        def __init__(self, prefix: str, name: str = ""):
            self._prefix = prefix
            super().__init__(name)

        async def connect(self, mock: bool = False, timeout: float = DEFAULT_TIMEOUT):
            await fill_pvi_entries(
                self, self._prefix + "PVI", timeout=timeout, mock=mock
            )
            await super().connect(mock=mock, timeout=timeout)

    async with DeviceCollector(mock=True):
        mock_panda = Panda("PANDAQSRV:", "mock_panda")

    assert mock_panda.name == "mock_panda"
    return mock_panda


async def test_seq_table_trigger_logic(mock_panda):
    trigger_logic = StaticSeqTableTriggerLogic(mock_panda.seq[1])
    seq_table = (
        SeqTable.row(outa1=True, outa2=True)
        + SeqTable.row(outa1=False, outa2=False)
        + SeqTable.row(outa1=True, outa2=False)
        + SeqTable.row(outa1=False, outa2=True)
    )
    seq_table_info = SeqTableInfo(sequence_table=seq_table, repeats=1)

    async def set_active(value: bool):
        await asyncio.sleep(0.1)
        set_mock_value(mock_panda.seq[1].active, value)

    await trigger_logic.prepare(seq_table_info)
    await asyncio.gather(trigger_logic.kickoff(), set_active(True))
    await asyncio.gather(trigger_logic.complete(), set_active(False))


async def test_pcomp_trigger_logic(mock_panda):
    trigger_logic = StaticPcompTriggerLogic(mock_panda.pcomp[1])
    pcomp_info = PcompInfo(
        start_postion=0,
        pulse_width=1,
        rising_edge_step=1,
        number_of_pulses=5,
        direction="Positive",
    )

    async def set_active(value: bool):
        await asyncio.sleep(0.1)
        set_mock_value(mock_panda.pcomp[1].active, value)

    await trigger_logic.prepare(pcomp_info)
    await asyncio.gather(trigger_logic.kickoff(), set_active(True))
    await asyncio.gather(trigger_logic.complete(), set_active(False))


@pytest.mark.parametrize(
    ["kwargs", "error_msg"],
    [
        (
            {
                "sequence_table_factory": lambda: SeqTable.row(outc2=1),
                "repeats": 0,
                "prescale_as_us": -1,
            },
            "Input should be greater than or equal to 0 "
            "[type=greater_than_equal, input_value=-1, input_type=int]",
        ),
        (
            {
                "sequence_table_factory": lambda: (
                    SeqTable.row(outc2=True)
                    + SeqTable.row(outc2=False)
                    + SeqTable.row(outc2=True)
                    + SeqTable.row(outc2=False)
                ),
                "repeats": -1,
            },
            "Input should be greater than or equal to 0 "
            "[type=greater_than_equal, input_value=-1, input_type=int]",
        ),
        (
            {
                "sequence_table_factory": lambda: 1,
                "repeats": 1,
            },
            "Input should be a valid dictionary or instance of SeqTable "
            "[type=model_type, input_value=1, input_type=int]",
        ),
    ],
)
def test_malformed_seq_table_info(kwargs, error_msg):
    with pytest.raises(ValidationError) as exc:
        SeqTableInfo(sequence_table=kwargs.pop("sequence_table_factory")(), **kwargs)
    assert error_msg in str(exc.value)


def test_malformed_trigger_in_seq_table():
    def full_seq_table(trigger):
        return SeqTable(
            repeats=np.array([1], dtype=np.int32),
            trigger=trigger,
            position=np.array([1], dtype=np.int32),
            time1=np.array([1], dtype=np.int32),
            outa1=np.array([1], dtype=np.bool_),
            outb1=np.array([1], dtype=np.bool_),
            outc1=np.array([1], dtype=np.bool_),
            outd1=np.array([1], dtype=np.bool_),
            oute1=np.array([1], dtype=np.bool_),
            outf1=np.array([1], dtype=np.bool_),
            time2=np.array([1], dtype=np.int32),
            outa2=np.array([1], dtype=np.bool_),
            outb2=np.array([1], dtype=np.bool_),
            outc2=np.array([1], dtype=np.bool_),
            outd2=np.array([1], dtype=np.bool_),
            oute2=np.array([1], dtype=np.bool_),
            outf2=np.array([1], dtype=np.bool_),
        )

    for attempted_table in [
        np.array(["A"], dtype="U32"),
        np.array(["Immediate"], dtype="U32"),
        {"Immediate"},
    ]:
        with pytest.raises(ValidationError) as exc:
            full_seq_table(attempted_table)
        assert "Input should be an instance of Sequence" in str(exc)

    with pytest.raises(ValidationError) as exc:
        full_seq_table(["A"])
    assert (
        "Input should be 'Immediate', 'BITA=0', 'BITA=1', 'BITB=0', 'BITB=1', "
        "'BITC...' [type=enum, input_value='A', input_type=str]"
    ) in str(exc)

    # Pydantic is able to infer type from these
    table = full_seq_table([SeqTrigger.IMMEDIATE])
    assert table.trigger == ["Immediate"] == [SeqTrigger.IMMEDIATE]
    table = full_seq_table(["Immediate"])
    assert table.trigger == ["Immediate"] == [SeqTrigger.IMMEDIATE]
