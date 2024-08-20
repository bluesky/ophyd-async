"""Used to test setting up signals for a PandA"""

import copy
from typing import Dict

import pytest

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    DeviceCollector,
    DeviceVector,
    NotConnected,
)
from ophyd_async.epics.pvi import create_children_from_annotations, fill_pvi_entries
from ophyd_async.epics.pvi._pvi import _PVIEntry  # noqa
from ophyd_async.fastcs.panda import (
    PcapBlock,
    PulseBlock,
    SeqBlock,
    SeqTable,
    SeqTrigger,
)


class DummyDict:
    def __init__(self, dict) -> None:
        self.dict = dict

    def todict(self):
        return self.dict


class MockPvi:
    def __init__(self, pvi: Dict[str, _PVIEntry]) -> None:
        self.pvi = pvi

    def get(self, item: str):
        return DummyDict(self.pvi)


class MockCtxt:
    def __init__(self, pvi: Dict[str, _PVIEntry]) -> None:
        self.pvi = copy.copy(pvi)

    def get(self, pv: str, timeout: float = 0.0):
        return MockPvi(self.pvi)


@pytest.fixture
async def panda_t():
    class CommonPandaBlocksNoData(Device):
        pcap: PcapBlock
        pulse: DeviceVector[PulseBlock]
        seq: DeviceVector[SeqBlock]

    class Panda(CommonPandaBlocksNoData):
        def __init__(self, prefix: str, name: str = ""):
            self._prefix = prefix
            create_children_from_annotations(self)
            super().__init__(name)

        async def connect(self, mock: bool = False, timeout: float = DEFAULT_TIMEOUT):
            await fill_pvi_entries(
                self, self._prefix + "PVI", timeout=timeout, mock=mock
            )
            await super().connect(mock=mock, timeout=timeout)

    yield Panda


@pytest.fixture
async def mock_panda(panda_t):
    async with DeviceCollector(mock=True):
        mock_panda = panda_t("PANDAQSRV:", "mock_panda")

    assert mock_panda.name == "mock_panda"
    yield mock_panda


def test_panda_names_correct(mock_panda):
    assert mock_panda.seq[1].name == "mock_panda-seq-1"
    assert mock_panda.pulse[1].name == "mock_panda-pulse-1"


def test_panda_name_set(panda_t):
    panda = panda_t(":", "panda")
    assert panda.name == "panda"


async def test_panda_children_connected(mock_panda):
    # try to set and retrieve from simulated values...
    table = (
        SeqTable.row(
            repeats=1,
            trigger=SeqTrigger.POSA_GT,
            position=3222,
            time1=5,
            outa1=True,
            outb1=False,
            outc1=False,
            outd1=True,
            oute1=True,
            outf1=True,
            time2=0,
            outa2=True,
            outb2=False,
            outc2=False,
            outd2=True,
            oute2=True,
            outf2=True,
        )
        + SeqTable.row(
            repeats=1,
            trigger=SeqTrigger.POSA_LT,
            position=-565,
            time1=0,
            outa1=False,
            outb1=False,
            outc1=True,
            outd1=True,
            oute1=False,
            outf1=False,
            time2=10,
            outa2=False,
            outb2=False,
            outc2=True,
            outd2=True,
            oute2=False,
            outf2=False,
        )
        + SeqTable.row(
            repeats=1,
            trigger=SeqTrigger.IMMEDIATE,
            position=0,
            time1=10,
            outa1=False,
            outb1=True,
            outc1=True,
            outd1=False,
            oute1=True,
            outf1=False,
            time2=10,
            outa2=False,
            outb2=True,
            outc2=True,
            outd2=False,
            oute2=True,
            outf2=False,
        )
        + SeqTable.row(
            repeats=32,
            trigger=SeqTrigger.IMMEDIATE,
            position=0,
            time1=10,
            outa1=True,
            outb1=True,
            outc1=False,
            outd1=True,
            oute1=False,
            outf1=False,
            time2=11,
            outa2=True,
            outb2=True,
            outc2=False,
            outd2=True,
            oute2=False,
            outf2=False,
        )
    )
    await mock_panda.pulse[1].delay.set(20.0)
    await mock_panda.seq[1].table.set(table)

    readback_pulse = await mock_panda.pulse[1].delay.get_value()
    readback_seq = await mock_panda.seq[1].table.get_value()

    assert readback_pulse == 20.0
    assert readback_seq == table


async def test_panda_with_missing_blocks(panda_pva, panda_t):
    panda = panda_t("PANDAQSRVI:")
    with pytest.raises(RuntimeError) as exc:
        await panda.connect()
    assert (
        str(exc.value)
        == "sub device `pcap:<class 'typing._ProtocolMeta'>` was not provided by pvi"
    )


async def test_panda_with_extra_blocks_and_signals(panda_pva, panda_t):
    panda = panda_t("PANDAQSRV:")
    await panda.connect()
    assert panda.extra  # type: ignore
    assert panda.extra[1]  # type: ignore
    assert panda.extra[2]  # type: ignore
    assert panda.pcap.newsignal  # type: ignore


async def test_panda_gets_types_from_common_class(panda_pva, panda_t):
    panda = panda_t("PANDAQSRV:")
    pcap = panda.pcap
    await panda.connect()

    # The pre-initialized blocks are now filled
    assert pcap is panda.pcap

    # sub devices have the correct types
    assert isinstance(panda.pcap, PcapBlock)
    assert isinstance(panda.seq[1], SeqBlock)
    assert isinstance(panda.pulse[1], PulseBlock)

    # others are just Devices
    assert isinstance(panda.extra, Device)

    # predefined signals get set up with the correct datatype
    assert panda.pcap.active._backend.datatype is bool

    # works with custom datatypes
    assert panda.seq[1].table._backend.datatype is SeqTable

    # others are given the None datatype
    assert panda.pcap.newsignal._backend.datatype is None


async def test_panda_block_missing_signals(panda_pva, panda_t):
    panda = panda_t("PANDAQSRVIB:")

    with pytest.raises(Exception) as exc:
        await panda.connect()
        assert (
            str(exc)
            == "PandA has a pulse block containing a width signal which has not been "
            + "retrieved by PVI."
        )


async def test_panda_unable_to_connect_to_pvi(panda_t):
    panda = panda_t("NON-EXISTENT:")

    with pytest.raises(NotConnected) as exc:
        await panda.connect(timeout=0.01)

    assert exc.value._errors == "pva://NON-EXISTENT:PVI"
