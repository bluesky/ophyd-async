import re
from enum import Enum
from typing import (
    Dict,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypedDict,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

import numpy as np
import numpy.typing as npt
from ophyd.v2.core import (
    Device,
    DeviceVector,
    DeviceCollector,
    connect_children,
    get_device_children,
)
from ophyd.v2.epics import EpicsSignalR, EpicsSignalRW, EpicsSignalW, EpicsSignalX
from bluesky import RunEngine

from p4p.client.thread import Context

ctxt = Context("pva")


class PulseBlock(Device):
    delay: EpicsSignalRW[float]
    width: EpicsSignalRW[float]

    _name = ""

    @property
    def name(self) -> str:
        return self._name

    def set_name(self, name: str):
        if name and not self._name:
            self._name = name

    async def connect(self, prefix: str = "", sim=False):
        await connect_children(self, prefix, sim)


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


class SeqBlock(Device):
    table: EpicsSignalRW[SeqTable]

    _name: str = ""

    @property
    def name(self) -> str:
        return self._name

    def set_name(self, name: str):
        if name and not self._name:
            self._name = name

    async def connect(self, prefix: str = "", sim=False):
        await connect_children(self, prefix, sim)


class PcapBlock(Device):
    _name: str = ""

    @property
    def name(self) -> str:
        return self._name

    def set_name(self, name: str):
        if name and not self._name:
            self._name = name

    async def connect(self, prefix: str = "", sim=False):
        await connect_children(self, prefix, sim)


class PVIEntry(TypedDict, total=False):
    d: str
    r: str
    rw: str
    w: str
    x: str


def block_name_number(block_name: str) -> Tuple[str, int]:
    m = re.match("^([a-z]+)([0-9]*)$", block_name)
    assert m, f"Expected '<block_name><block_num>', got '{block_name}'"
    name, num = m.groups()
    return name, int(num or 1)


# in sim mode, this should be called with a timeout of 0.0.
async def pvi_get(pv: str, timeout: float = 5.0) -> Dict[str, PVIEntry]:
    pv_info: Dict[str, Dict[str, str]] = {}
    try:
        pv_info = ctxt.get(pv, timeout=timeout).get("pvi").todict()
    except TimeoutError:
        # log here that it couldn't access it.
        raise Exception("Cannot get the PV.")

    result = {}

    for attr_name, attr_info in pv_info.items():
        result[attr_name] = PVIEntry(**attr_info)
    return result


def check_anno(
    signal_cls: Type, field_annos: Dict[str, Type], field_name
) -> Optional[Type]:
    field_anno = field_annos.get(field_name)
    if field_anno:
        anno_signal_cls = get_origin(field_anno)
        assert (
            signal_cls == anno_signal_cls
        ), f"Expected {anno_signal_cls}, got {signal_cls}"
        args = get_args(field_anno)
        if args:
            return args[0]
    return None


class PandA(Device):
    _name = ""
    # Attribute interface for selected blocks
    pulse: DeviceVector[PulseBlock]
    seq: DeviceVector[SeqBlock]
    pcap: PcapBlock
    # All blocks available with numbered names, e.g. self.seq[1], self.pcap

    def __init__(self, prefix: str, name: str = "") -> None:
        self._init_prefix = prefix
        # doesn't make sense calling set_name as no child devices setup initially.
        # this all happens after connect() has been called...

    @property
    def name(self) -> str:
        return self._name

    # TODO: getattr instead
    def set_name(self, name: str = ""):
        self._name = name
        for child_name, child in get_device_children(self):
            child.set_name(f"{name}-{child_name.rstrip('_')}")
            child.parent = self
            # for block_name, block in self.blocks.items():
            #     block.set_name(f"{name}-{block_name.lower()}")
            #     block.parent = self

    async def _make_block(self, block_name: str, block_pv: str, sim: bool):
        name, num = block_name_number(block_name)
        anno = get_type_hints(self).get(name)
        if anno:
            # We know what type it should be, so make one
            args = get_args(anno)
            if args:
                # Anno is Tuple(block_cls,)
                block = args[0]()
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
        assert not hasattr(
            self, block_name
        ), f"Name clash, self.{block_name} = {getattr(self, block_name)}"
        setattr(self, block_name, block)

        # self now has 'block1' and 'block[1]' PulseBlocks.
        # pvi_get gets you a dict of [str, PVIEntry]
        block_pvi = await pvi_get(block_pv)
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
                raise ValueError(
                    f"Can't make {block_name}.{field_name} from {field_pvi}"
                )
            setattr(block, field_name, signal)

    async def connect(self, prefix: str = "", sim=False):
        panda_pvi = await pvi_get(self._init_prefix + prefix + ":PVI")

        for block_name, block_pvi in panda_pvi.items():
            assert list(block_pvi) == [
                "d"
            ], f"Expected PandA to only contain blocks, got {block_pvi}"
            await self._make_block(block_name, block_pvi["d"], sim=sim)

        await connect_children(self, prefix, sim)


# RE = RunEngine()

# # todo: let DeviceCollector have separate order for naming/connecting?
# # In this case, can only name after connect.
# with DeviceCollector(set_name=False, sim=True):
#     somepanda = PandA("PANDAQSRV")

# somepanda.set_name("somepanda")
# print("aha")
