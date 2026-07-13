"""Used to test setting up signals for a PandA"""

import copy
from typing import Any

import numpy as np
import pytest

from ophyd_async.core import (
    Device,
    DeviceVector,
    NotConnectedError,
    init_devices,
)
from ophyd_async.fastcs.core import fastcs_connector
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
    def __init__(self, pvi: dict[str, Any]) -> None:
        self.pvi = pvi

    def get(self, item: str):
        return DummyDict(self.pvi)


class MockCtxt:
    def __init__(self, pvi: dict[str, Any]) -> None:
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
        def __init__(self, uri: str, name: str = ""):
            super().__init__(
                name=name, connector=fastcs_connector(uri, self, "Is it ok?")
            )

    yield Panda


@pytest.fixture
async def mock_panda(panda_t):
    async with init_devices(mock=True):
        mock_panda = panda_t("PANDAQSRV:")

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
    table = SeqTable(
        repeats=np.array([1, 1, 1, 32]).astype(np.uint16),
        trigger=(
            SeqTrigger.POSA_GT,
            SeqTrigger.POSA_LT,
            SeqTrigger.IMMEDIATE,
            SeqTrigger.IMMEDIATE,
        ),
        position=np.array([3222, -565, 0, 0], dtype=np.int32),
        time1=np.array([5, 0, 10, 10]).astype(np.uint32),  # TODO: change below syntax.
        outa1=np.array([1, 0, 0, 1]).astype(np.bool_),
        outb1=np.array([0, 0, 1, 1]).astype(np.bool_),
        outc1=np.array([0, 1, 1, 0]).astype(np.bool_),
        outd1=np.array([1, 1, 0, 1]).astype(np.bool_),
        oute1=np.array([1, 0, 1, 0]).astype(np.bool_),
        outf1=np.array([1, 0, 0, 0]).astype(np.bool_),
        time2=np.array([0, 10, 10, 11]).astype(np.uint32),
        outa2=np.array([1, 0, 0, 1]).astype(np.bool_),
        outb2=np.array([0, 0, 1, 1]).astype(np.bool_),
        outc2=np.array([0, 1, 1, 0]).astype(np.bool_),
        outd2=np.array([1, 1, 0, 1]).astype(np.bool_),
        oute2=np.array([1, 0, 1, 0]).astype(np.bool_),
        outf2=np.array([1, 0, 0, 0]).astype(np.bool_),
    )

    await mock_panda.pulse[1].delay.set(20.0)
    await mock_panda.seq[1].table.set(table)

    readback_pulse = await mock_panda.pulse[1].delay.get_value()
    readback_seq = await mock_panda.seq[1].table.get_value()

    assert readback_pulse == 20.0
    assert readback_seq == table


async def test_panda_unable_to_connect_to_pvi(panda_t):
    panda = panda_t("NON-EXISTENT:")

    with pytest.raises(NotConnectedError) as exc:
        await panda.connect(timeout=0.01)

    assert exc.value._errors == "pva://NON-EXISTENT:PVI"


async def test_panda_gets_types_from_common_class(panda_t):
    """Fold-forward of the deleted ``tests/system_tests/fastcs/panda/
    test_panda_connect.py::test_panda_gets_types_from_common_class`` (issue
    #1321, item 7 -- PandA system-test cleanup, unblocked by item 2's generic
    PVI-protocol coverage in ``tests/system_tests/epics/core/
    test_pvi_nested.py``).

    Kept, because these are all resolvable purely from ``PcapBlock``/
    ``SeqBlock``/``PulseBlock``'s own class annotations, needing at most
    ``connect(mock=True)`` and no live PVI tree at all (see
    ``PviDeviceConnector.create_children_from_annotations``, which runs at
    ``Device.__init__`` time from the annotations alone, vs. ``connect_real``,
    which is the only thing that ever talks to a network):

    - sub-block type resolution (``panda.pcap`` is a ``PcapBlock``,
      ``panda.seq[1]`` is a ``SeqBlock``, ``panda.pulse[1]`` is a
      ``PulseBlock``) -- verified this holds even before any ``connect()``
      for non-vector blocks, and right after ``connect(mock=True)`` for
      vector ones (``DeviceVector`` entries are only populated at connect
      time, mock or real).
    - the pre-initialised ``pcap`` block is the same object after
      ``connect()``, i.e. connecting doesn't replace annotation-created
      children.
    - predefined-signal datatype resolution (``pcap.active``'s backend
      datatype is ``bool``).
    - custom-datatype resolution (``seq[1].table``'s backend datatype is
      ``SeqTable``).

    Dropped, with no unit-test equivalent (confirmed by direct experiment:
    ``connect(mock=True)`` raises ``AttributeError`` for both, since mock
    connect has no live PVI tree to walk):

    - ``panda.pcap.newsignal`` and its ``NO_ARG_VOID_SIGNATURE`` signature
      check -- ``newsignal`` is not declared anywhere in ``PcapBlock``; it
      only ever appears by walking a live PVI tree in
      ``PviDeviceConnector.connect_real`` (gated behind the
      ``INCLUDE_EXTRA_SIGNAL`` macro in the old system test's IOC database).
    - ``panda.extra`` and its ``isinstance(..., DeviceVector)`` check --
      same story, ``extra`` is a block gated behind ``INCLUDE_EXTRA_BLOCK``
      in the old IOC database and only discoverable live.

    Both are specific (PandA-flavoured) instances of "a Device that never
    predeclares a signal/sub-device still gets one from a live PVI tree",
    which issue #1321 item 2 already covers generically, independent of
    PandA, in ``tests/system_tests/epics/core/test_pvi_nested.py`` -- so
    dropping them here is not a unique coverage loss.
    """
    panda = panda_t("PANDAQSRV:")
    pcap = panda.pcap
    await panda.connect(mock=True)

    # The pre-initialized blocks are not replaced by connect()
    assert pcap is panda.pcap

    # sub devices have the correct types
    assert isinstance(panda.pcap, PcapBlock)
    assert isinstance(panda.seq[1], SeqBlock)
    assert isinstance(panda.pulse[1], PulseBlock)

    # predefined signals get set up with the correct datatype
    assert panda.pcap.active._connector.backend.datatype is bool

    # works with custom datatypes
    assert panda.seq[1].table._connector.backend.datatype is SeqTable
