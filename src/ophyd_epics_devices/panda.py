import re
from enum import Enum
from typing import (
    Callable,
    Dict,
    FrozenSet,
    Optional,
    Sequence,
    Tuple,
    TypedDict,
    get_args,
    get_origin,
    get_type_hints,
)

import numpy as np
import numpy.typing as npt
from ophyd.v2.core import (
    Device,
    DeviceVector,
    Signal,
    SignalRW,
    SignalX,
    SimSignalBackend,
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
    arm: SignalX


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


class PandA(Device):
    pulse: DeviceVector[PulseBlock]
    seq: DeviceVector[SeqBlock]
    pcap: PcapBlock

    def __init__(self, prefix: str, name: str = "") -> None:
        self._init_prefix = prefix

        self.pvi_mapping: Dict[FrozenSet[str], Callable[..., Signal]] = {
            frozenset({"r", "w"}): lambda dtype, rpv, wpv: epics_signal_rw(
                dtype, rpv, wpv
            ),
            frozenset({"rw"}): lambda dtype, rpv, wpv: epics_signal_rw(dtype, rpv, wpv),
            frozenset({"r"}): lambda dtype, rpv, wpv: epics_signal_r(dtype, rpv),
            frozenset({"w"}): lambda dtype, rpv, wpv: epics_signal_w(dtype, wpv),
            frozenset({"x"}): lambda dtype, rpv, wpv: epics_signal_x(wpv),
        }

    def verify_block(self, name: str, num: int):
        """Given a block name and number, return information about a block."""
        anno = get_type_hints(self).get(name)

        block: Device = Device()

        if anno:
            type_args = get_args(anno)
            block = type_args[0]() if type_args else anno()

            if not type_args:
                assert num == 1, f"Only expected one {name} block, got {num}"

        return block

    async def _make_block(self, name: str, num: int, block_pv: str, sim: bool = False):
        """Makes a block given a block name containing relevant signals.

        Loops through the signals in the block (found using type hints), if not in
        sim mode then does a pvi call, and identifies this signal from the pvi call.
        """
        block = self.verify_block(name, num)

        field_annos = get_type_hints(block)
        block_pvi = await pvi_get(block_pv) if not sim else None

        # finds which fields this class actually has, e.g. delay, width...
        for sig_name, sig_type in field_annos.items():
            origin = get_origin(sig_type)
            args = get_args(sig_type)

            # if not in sim mode,
            if block_pvi:
                # try to get this block in the pvi.
                entry: Optional[PVIEntry] = block_pvi.get(sig_name)
                if entry is None:
                    raise Exception(
                        f"{self.__class__.__name__} has a {name} block containing a "
                        + f"{sig_name} signal which has not been retrieved by PVI."
                    )

                pvs = [entry[i] for i in frozenset(entry.keys())]  # type: ignore
                if len(pvs) == 1:
                    read_pv = write_pv = pvs[0]
                else:
                    read_pv, write_pv = pvs

                signal_factory = self.pvi_mapping[frozenset(entry.keys())]
                signal = signal_factory(
                    args[0] if len(args) > 0 else None,
                    "pva://" + read_pv,
                    "pva://" + write_pv,
                )

            else:
                backend = SimSignalBackend(args[0] if len(args) > 0 else None, block_pv)
                signal = SignalX(backend) if not origin else origin(backend)

            setattr(block, sig_name, signal)

        return block

    async def _make_untyped_block(self, block_pv: str):
        """Populates a block using PVI information.

        This block is not typed as part of the PandA interface but needs to be
        included dynamically anyway.
        """
        block = Device()
        block_pvi = await pvi_get(block_pv)

        for signal_name, signal_pvi in block_pvi.items():
            signal_factory = self.pvi_mapping[frozenset(signal_pvi.keys())]

            pvs = [signal_pvi[i] for i in frozenset(signal_pvi.keys())]  # type: ignore
            if len(pvs) == 1:
                read_pv = write_pv = pvs[0]
            else:
                read_pv, write_pv = pvs

            signal = signal_factory(None, "pva://" + read_pv, "pva://" + write_pv)

            setattr(block, signal_name, signal)

        return block

    def set_attribute(self, name, num, block):
        anno = get_type_hints(self).get(name)

        # get_origin to see if it's a device vector.
        if (anno == DeviceVector[PulseBlock]) or (anno == DeviceVector[SeqBlock]):
            self.__dict__.setdefault(name, DeviceVector())[num] = block
        else:
            setattr(self, name, block)

    async def connect(self, sim=False) -> None:
        """Initialises all blocks and connects them.

        First, checks for pvi information. If it exists, make all blocks from this.
        Then, checks that all required blocks in the PandA have been made.

        If there's no pvi information, that's because we're in sim mode. In that case,
        makes all required blocks.
        """
        pvi = await pvi_get(self._init_prefix + ":PVI") if not sim else None
        hints = get_type_hints(self)

        # create all the blocks pvi says it should have,
        if pvi:
            for block_name, block_pvi in pvi.items():
                name, num = block_name_number(block_name)

                if name in hints:
                    block = await self._make_block(name, num, block_pvi["d"])
                else:
                    block = await self._make_untyped_block(block_pvi["d"])

                self.set_attribute(name, num, block)

        # then check if the ones defined in this class are at least made.
        for block_name in hints.keys():
            pv = "sim://"

            if pvi is not None:
                pvi_name = block_name

                if get_origin(hints[block_name]) == DeviceVector:
                    pvi_name += "1"

                entry: Optional[PVIEntry] = pvi.get(pvi_name)

                assert entry, f"Expected PandA to contain {block_name} block."
                assert list(entry) == [
                    "d"
                ], f"Expected PandA to only contain blocks, got {entry}"
            else:
                # or, if there's no pvi info, just make the minimum blocks needed
                block = await self._make_block(block_name, 1, pv, sim=sim)
                self.set_attribute(block_name, 1, block)

        self.set_name(self.name)
        await super().connect(sim)
