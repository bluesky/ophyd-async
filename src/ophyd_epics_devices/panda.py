import asyncio
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
from ophyd.v2.core import (
    Device,
    DeviceCollector,
    DeviceVector,
    SignalR,
    SignalRW,
    SignalW,
    connect_children,
)
from ophyd.v2.epics import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_w,
    epics_signal_x,
)
from p4p.client.thread import Context

ctxt = Context("pva")


class PulseBlock(Device):
    delay: SignalRW[float]
    width: SignalRW[float]


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
    table: SignalRW[SeqTable]


class PcapBlock(Device):
    ...


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
        result[attr_name] = PVIEntry(**attr_info)  # type: ignore
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
    pulse: DeviceVector[PulseBlock]
    seq: DeviceVector[SeqBlock]
    pcap: PcapBlock

    def __init__(self, prefix: str, name: str = "") -> None:
        self._init_prefix = prefix

    async def _make_block(self, name: str, num: int, block_pv: str, sim: bool):
        anno = get_type_hints(self).get(name)

        block: Device = Device()
        field_annos = {}

        if anno:
            type_args = get_args(anno)
            block = type_args[0]() if type_args else anno()

            if not type_args:
                assert num == 1, f"Only expected one {name} block, got {num}"

            field_annos = get_type_hints(block)

        block_pvi = await pvi_get(block_pv)
        for field_name, field_pvi in block_pvi.items():
            if "x" in field_pvi:
                signal = epics_signal_x("pva://" + field_pvi["x"])
            elif "rw" in field_pvi:
                typ = check_anno(SignalRW, field_annos, field_name)
                signal = epics_signal_rw(typ, "pva://" + field_pvi["rw"])
            elif "r" in field_pvi and "w" in field_pvi:
                typ = check_anno(SignalRW, field_annos, field_name)
                signal = epics_signal_rw(
                    typ, "pva://" + field_pvi["r"], "pva://" + field_pvi["w"]
                )
            elif "r" in field_pvi:
                typ = check_anno(SignalR, field_annos, field_name)
                signal = epics_signal_r(typ, "pva://" + field_pvi["r"])
            elif "w" in field_pvi:
                typ = check_anno(SignalW, field_annos, field_name)
                signal = epics_signal_w(typ, "pva://" + field_pvi["w"])
            else:
                raise ValueError(
                    f"Can't make {name}{num}.{field_name} from {field_pvi}"
                )
            setattr(block, field_name, signal)

        return block

    async def connect(self, sim=False):
        panda_pvi = await pvi_get(self._init_prefix + ":PVI")

        for block_name, block_pvi in panda_pvi.items():
            assert list(block_pvi) == [
                "d"
            ], f"Expected PandA to only contain blocks, got {block_pvi}"
            name, num = block_name_number(block_name)
            block = await self._make_block(name, num, block_pvi["d"], sim=sim)

            anno = get_type_hints(self).get(name)

            if (anno == DeviceVector[PulseBlock]) or (anno == DeviceVector[SeqBlock]):
                self.__dict__.setdefault(name, DeviceVector())[num] = block
            else:
                setattr(self, name, block)

        self.set_name(self.name)
        await connect_children(self, sim)


async def make_panda():
    async with DeviceCollector():
        sim_panda = PandA("PANDAQSRV")

    print("ah")
    print(sim_panda)


if __name__ == "__main__":
    asyncio.run(make_panda())
