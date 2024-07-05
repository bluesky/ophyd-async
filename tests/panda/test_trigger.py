import asyncio

import numpy as np
import pytest

from ophyd_async.core import set_mock_value
from ophyd_async.core.device import DEFAULT_TIMEOUT, DeviceCollector
from ophyd_async.epics.pvi.pvi import fill_pvi_entries
from ophyd_async.panda import (
    CommonPandaBlocks,
    PcompInfo,
    SeqTable,
    SeqTableInfo,
    StaticPcompTriggerLogic,
    StaticSeqTableTriggerLogic,
)


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


async def test_seq_table_trigger_logic_has_given_methods(mock_panda):
    trigger_logic = StaticSeqTableTriggerLogic(mock_panda.seq[1])
    assert hasattr(trigger_logic, "prepare")
    assert hasattr(trigger_logic, "kickoff")
    assert hasattr(trigger_logic, "complete")
    assert hasattr(trigger_logic, "stop")


async def test_seq_table_trigger_logic(mock_panda):
    trigger_logic = StaticSeqTableTriggerLogic(mock_panda.seq[1])
    seq_table = SeqTable(
        outa1=np.array([1, 2, 3, 4, 5]), outa2=np.array([1, 2, 3, 4, 5])
    )
    seq_table_info = SeqTableInfo(sequence_table=seq_table, repeats=1)

    async def set_active(value: bool):
        await asyncio.sleep(0.1)
        set_mock_value(mock_panda.seq[1].active, value)

    await trigger_logic.prepare(seq_table_info)
    await asyncio.gather(trigger_logic.kickoff(), set_active(True))
    await asyncio.gather(trigger_logic.complete(), set_active(False))


async def test_pcomp_trigger_logic_has_given_methods(mock_panda):
    trigger_logic = StaticPcompTriggerLogic(mock_panda.pcomp[1])
    assert hasattr(trigger_logic, "prepare")
    assert hasattr(trigger_logic, "kickoff")
    assert hasattr(trigger_logic, "complete")
    assert hasattr(trigger_logic, "stop")


async def test_pcomp_trigger_logic(mock_panda):
    trigger_logic = StaticPcompTriggerLogic(mock_panda.pcomp[1])
    pcomp_info = PcompInfo(0, 1, 1, 5, "POSITIVE")

    async def set_active(value: bool):
        await asyncio.sleep(0.1)
        set_mock_value(mock_panda.pcomp[1].active, value)

    await trigger_logic.prepare(pcomp_info)
    await asyncio.gather(trigger_logic.kickoff(), set_active(True))
    await asyncio.gather(trigger_logic.complete(), set_active(False))
