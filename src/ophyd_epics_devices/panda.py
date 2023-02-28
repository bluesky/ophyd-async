import re
from enum import Enum
from typing import (
    Dict,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypedDict,
    get_args,
    get_origin,
    get_type_hints,
)

import numpy as np
import numpy.typing as npt
from ophyd.v2.core import Device
from ophyd.v2.epics import EpicsSignalR, EpicsSignalRW, EpicsSignalW, EpicsSignalX


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

class PcapBlock:
    pass
class PVIEntry(TypedDict, total=False):
    d: str
    r: str
    rw: str
    w: str


def block_name_number(block_name: str) -> Tuple[str, int]:
    m = re.match("^([a-z]+)([0-9]*)$", block_name)
    assert m, f"Expected '<block_name><block_num>', got '{block_name}'"
    name, num = m.groups()
    return name, int(num or 1)

async def pvi_get(pv: str, sim: bool) -> Dict[str, PVIEntry]:
    ...

def check_anno(signal_cls: Type, field_annos: Dict[str, Type], field_name) -> Optional[Type]:
    field_anno = field_annos.get(field_name)    
    if field_anno:
        anno_signal_cls = get_origin(field_anno)
        assert signal_cls == anno_signal_cls, f"Expected {anno_signal_cls}, got {signal_cls}"
        args = get_args(field_anno)
        if args:  
            return args[0]
    return None

class PandA(Device):
    _name = ""
    # Attribute interface for selected blocks
    pulse: Dict[int, PulseBlock]
    seq: Dict[int, SeqBlock]
    pcap: PcapBlock
    # All blocks available with numbered names, e.g. self.seq1

    def __init__(self, prefix: str, name: str = "") -> None:
        self._init_prefix = prefix
        self.set_name(name)

    @property
    def name(self) -> str:
        return self._name

    # TODO: getattr instead
    def set_name(self, name: str = ""):
        if name and not self._name:
            self._name = name
            for block_name, block in self.blocks.items():
                block.set_name(f"{name}-{block_name.lower()}")
                block.parent = self

    async def _make_block(self, block_name: str, block_pv: str, sim: bool):
        name, num = block_name_number(block_name)
        anno = get_type_hints(self).get(name)
        if anno:
            # We know what type it should be, so make one
            args = get_args(anno)
            if args:
                # Anno is Dict[str, block_cls]       
                block = args[1]()
                # Make dict if it doesn't already exist, and add block to it
                self.__dict__.setdefault(name, {})[num] = block
            else:
                # Anno is just the block class
                assert num == 1, f"Only expected one {name} block, got {num}"
                block = anno()
            field_annos = get_type_hints(block)
        else:
            # Make a generic device
            block = Device()
            field_annos = {}
        assert not hasattr(self, block_name), f"Name clash, self.{block_name} = {getattr(self, block_name)}"
        setattr(self, block_name, block)
        block_pvi = await pvi_get(block_pv, sim)        
        for field_name, field_pvi in block_pvi.items():            
            if "x" in field_pvi:
                check_anno(EpicsSignalX, field_annos, field_name)
                signal = EpicsSignalX(field_pvi["x"])
            elif "rw" in field_pvi:
                typ = check_anno(EpicsSignalRW, field_annos, field_name)
                signal = EpicsSignalRW(typ, field_pvi["rw"])
            elif "r" in field_pvi and "w" in field_pvi:
                typ = check_anno(EpicsSignalRW, field_annos, field_name)
                signal = EpicsSignalRW(typ, field_pvi["r"], field_pvi["w"])
            elif "r" in field_pvi:
                typ = check_anno(EpicsSignalR, field_annos, field_name)
                signal = EpicsSignalR(typ, field_pvi["r"])
            elif "w" in field_pvi:
                typ = check_anno(EpicsSignalW, field_annos, field_name)
                signal = EpicsSignalW(typ, field_pvi["w"])
            else:
                raise ValueError(f"Can't make {block_name}.{field_name} from {field_pvi}")
            setattr(block, field_name, signal)
     
    async def connect(self, prefix: str = "", sim=False):
        panda_pvi = await pvi_get(self._init_prefix + prefix + ":PVI", sim)
        for block_name, block_pvi in panda_pvi.items():
            assert list(block_pvi) == ["d"], f"Expected PandA to only contain blocks, got {block_pvi}"
            await self._make_block(block_name, block_pvi["d"])
        # TODO: connect_children here
