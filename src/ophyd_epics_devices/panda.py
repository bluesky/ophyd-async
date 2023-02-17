from enum import Enum
from typing import Dict, Protocol, Sequence, Type, TypedDict, TypeVar, runtime_checkable

import numpy as np
import numpy.typing as npt
from ophyd.v2.core import Device
from ophyd.v2.epics import EpicsSignalRW


class PulseBlock(Device):
    delay: EpicsSignalRW[float]
    width: EpicsSignalRW[float]


class SeqTrigger(Enum):
    IMMEDIATE = "Immediate"
    BITA_0 = "BITA=0"
    BITA_1 = "BITA=1"
    BITB_0 = "BITB=0"
    BITB_1 = "BITB=1"
    BITC_0 = "BITC=0"
    BITC_1 = "BITC=1"
    POSA_GT = "POSA>=POSITION"
    POSA_LT = "POSA<=POSITION"
    POSB_GT = "POSB>=POSITION"
    POSB_LT = "POSB<=POSITION"
    POSC_GT = "POSC>=POSITION"
    POSC_LT = "POSC<=POSITION"


class SeqTable(TypedDict):
    repeats: npt.NDArray[np.uint16]
    trigger: Sequence[SeqTrigger]
    position: npt.NDArray[np.int32]
    time1: npt.NDArray[np.uint32]
    outa1: npt.NDArray[np.bool_]
    outb1: npt.NDArray[np.bool_]
    outc1: npt.NDArray[np.bool_]
    outd1: npt.NDArray[np.bool_]
    oute1: npt.NDArray[np.bool_]
    outf1: npt.NDArray[np.bool_]
    time2: npt.NDArray[np.uint32]
    outa2: npt.NDArray[np.bool_]
    outb2: npt.NDArray[np.bool_]
    outc2: npt.NDArray[np.bool_]
    outd2: npt.NDArray[np.bool_]
    oute2: npt.NDArray[np.bool_]
    outf2: npt.NDArray[np.bool_]


class SeqBlock:
    table: EpicsSignalRW[SeqTable]


class Blocks(TypedDict):
    PULSE: Dict[int, PulseBlock]
    SEQ: Dict[int, SeqBlock]


class PandA(Device):
    _name = ""

    def __init__(self, prefix: str, name: str = "") -> None:
        self._init_prefix = prefix
        # Public interface for selected blocks
        self.blocks = Blocks(PULSE={}, SEQ={})
        # Private interface for all blocks
        self._all_blocks: Dict[str, Device] = {}
        self.set_name(name)

    @property
    def name(self) -> str:
        return self._name

    def set_name(self, name: str = ""):
        if name and not self._name:
            self._name = name
            for block_name, block in self._all_blocks.items():
                block.set_name(f"{name}-{block_name}")
                block.parent = self

    async def _make_block(self, block_name: str, block_pv: str, sim: bool):
        block_pvi = await pvi_get(block_pv, sim)
        block_base = block_name.rstrip()

    async def connect(self, prefix: str = "", sim=False):
        panda_pvi = await pvi_get(self._init_prefix + prefix, sim)
        for block_name, block_pv in panda_pvi.items():
            await self._make_block(block_name, block_pv)
