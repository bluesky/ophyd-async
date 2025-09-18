"""Used to test setting up signals for a PandA"""

import os
import re

import pytest

from ophyd_async.core import (
    Device,
    DeviceVector,
)
from ophyd_async.fastcs.core import fastcs_connector
from ophyd_async.fastcs.panda import (
    PcapBlock,
    PulseBlock,
    SeqBlock,
    SeqTable,
)


@pytest.fixture
async def panda_t():
    class CommonPandaBlocksNoData(Device):
        pcap: PcapBlock
        pulse: DeviceVector[PulseBlock]
        seq: DeviceVector[SeqBlock]

    class Panda(CommonPandaBlocksNoData):
        def __init__(self, uri: str, name: str = ""):
            super().__init__(
                name=name, connector=fastcs_connector(self, uri, "Is it ok?")
            )

    yield Panda


@pytest.mark.timeout(15.0 if os.name == "nt" else 4.0)
async def test_panda_with_missing_blocks(panda_pva, panda_t):
    panda = panda_t("PANDAQSRVI:", name="mypanda")
    with pytest.raises(
        RuntimeError,
        match=re.escape(
            "mypanda: cannot provision ['pcap'] from PANDAQSRVI:PVI: "
            "{'pulse': [None, {'d': 'PANDAQSRVI:PULSE1:PVI'}],"
            " 'seq': [None, {'d': 'PANDAQSRVI:SEQ1:PVI'}]}\nIs it ok?"
        ),
    ):
        await panda.connect()


@pytest.mark.timeout(15.0 if os.name == "nt" else 4.1)
async def test_panda_with_extra_blocks_and_signals(panda_pva, panda_t):
    panda = panda_t("PANDAQSRV:")
    await panda.connect()
    assert panda.extra  # type: ignore
    assert panda.extra[1]  # type: ignore
    assert panda.extra[2]  # type: ignore
    assert panda.pcap.newsignal  # type: ignore


@pytest.mark.timeout(15.0 if os.name == "nt" else 5.1)
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
    assert isinstance(panda.extra, DeviceVector)

    # predefined signals get set up with the correct datatype
    assert panda.pcap.active._connector.backend.datatype is bool

    # works with custom datatypes
    assert panda.seq[1].table._connector.backend.datatype is SeqTable

    # others are given the None datatype
    assert panda.pcap.newsignal._connector.backend.datatype is None


@pytest.mark.timeout(15.0 if os.name == "nt" else 4.5)
async def test_panda_block_missing_signals(panda_pva, panda_t):
    panda = panda_t("PANDAQSRVIB:")

    with pytest.raises(Exception) as exc:
        await panda.connect()
        assert (
            str(exc)
            == "PandA has a pulse block containing a width signal which has not been "
            + "retrieved by PVI."
        )
