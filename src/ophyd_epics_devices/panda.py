import asyncio
import re
from enum import Enum
from typing import (
    Callable,
    Dict,
    KeysView,
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
    DeviceCollector,
    DeviceVector,
    Signal,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
    get_device_children,
    wait_for_connection,
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

    @classmethod
    def make_block(self):
        pass


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
    test: SignalR[int]
    ...


class PVIEntry(TypedDict, total=False):
    d: str
    r: str
    rw: str
    w: str
    x: str


PVIEntryKeys = KeysView[PVIEntry]


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
        try:
            field_annos = get_type_hints(block)
        except NameError:
            # this only happens because if you try to get_type_hints on a pcap block,
            # as its empty it'll complain. I need to actually populate it...
            return None

        pvi_mapping: Dict[str, Tuple[Type[Signal], Callable[..., Signal]]] = {
            "rw": (SignalRW, lambda dtype, rpv, wpv: epics_signal_rw(dtype, rpv, wpv)),
            "r": (SignalR, lambda dtype, rpv, wpv: epics_signal_r(dtype, rpv)),
            "w": (SignalW, lambda dtype, rpv, wpv: epics_signal_w(dtype, wpv)),
            "x": (SignalX, lambda dtype, rpv, wpv: epics_signal_x(wpv)),
        }

        block_pvi = await pvi_get(block_pv) if not sim else None

        # finds which fields this class actually has, e.g. delay, width...
        for sig_name, sig_type in field_annos.items():
            origin = get_origin(sig_type)

            # if not in sim mode,
            if block_pvi:
                # try to get this block in the pvi.
                entry: Optional[PVIEntry] = block_pvi.get(sig_name)
                if entry is None:
                    raise Exception(
                        f"{self.__class__.__name__} has a {name} block containing a "
                        + f"{sig_name} signal which has not been retrieved by PVI."
                    )

                for key, value in entry.items():
                    typed_value = cast(str, value)
                    signal_type, signal_factory = pvi_mapping[key]
                    annotation = check_anno(signal_type, field_annos, sig_name)
                    signal = signal_factory(
                        annotation, "pva://" + typed_value, "pva://" + typed_value
                    )

                if entry.keys() == {"r", "w"}:
                    signal = epics_signal_rw(
                        check_anno(SignalRW, field_annos, sig_name),
                        "pva://" + entry["r"],
                        "pva://" + entry["w"],
                    )
            else:
                if not origin:
                    signal = epics_signal_x("pva://")
                else:
                    pvi_equivalent = origin.__name__.lower().split("signal")[-1]
                    dtype = get_args(sig_type)[0]

                    signal_factory = pvi_mapping[pvi_equivalent][1]
                    signal = signal_factory(dtype, "pva://", "pva://")

            setattr(block, sig_name, signal)

            # TODO: make more arbitrary blocks if they're in PVI but not this class?
            # that sounds kind of dumb though. It's already handled in the previous
            # step.
        return block

    def set_attribute(self, name, num, block):
        anno = get_type_hints(self).get(name)

        if (anno == DeviceVector[PulseBlock]) or (anno == DeviceVector[SeqBlock]):
            self.__dict__.setdefault(name, DeviceVector())[num] = block
        else:
            setattr(self, name, block)

    async def connect(self, sim=False) -> None:
        """Initialises all blocks and connects them.

        This method loops through all properties of this class (pulse, seq and pcap)
        and for each one works out a pv name. By default it is set to "sim://" because
        the initial idea was you could have a panda block with some sim blocks. But it
        tries to query pvi and get that info for the 1st block.

        Then it checks if pvi has any more blocks other than just 1, and sets those up.

        simulated and non-simulated blocks are connected accordingly.
        """
        pvi = await pvi_get(self._init_prefix + ":PVI") if not sim else None
        hints = get_type_hints(self)
        sim_blocks = []

        # set up bare minimum blocks,
        for block_name in hints.keys():
            pv = "sim://"

            if pvi is not None:
                entry: Optional[PVIEntry] = pvi.get(block_name + "1")

                if entry is None:
                    print(
                        "ERROR: This PVIEntry does not contain required block: "
                        + f"{block_name}. Using simulated block."
                    )
                else:
                    assert list(entry) == [
                        "d"
                    ], f"Expected PandA to only contain blocks, got {entry}"
                    pv = entry["d"]

            block = await self._make_block(
                block_name, 1, pv, sim=True if pv == "sim://" else False
            )
            self.set_attribute(block_name, 1, block)
            if pv.startswith("sim"):
                sim_blocks.append(block_name)

        # check for more from pvi info (if available)
        if pvi:
            for block_name, block_pvi in pvi.items():
                name, num = block_name_number(block_name)
                if getattr(self, name).get(num) is None:
                    block = await self._make_block(name, num, block_pvi["d"])
                    self.set_attribute(name, num, block)

        # set name and connect
        self.set_name(self.name)
        if not sim:
            non_sim_coros = {
                name: child_device.connect(False)
                for name, child_device in get_device_children(self)
                if name not in sim_blocks
            }
            sim_coros = {
                name: child_device.connect(True)
                for name, child_device in get_device_children(self)
                if name in sim_blocks
            }
            await wait_for_connection(**non_sim_coros, **sim_coros)
        else:
            await super().connect(True)


async def make_panda():
    async with DeviceCollector(sim=False):
        sim_panda = PandA("PANDAQSRV")

    print(sim_panda)


if __name__ == "__main__":
    asyncio.run(make_panda())


# TALK TO TOM ABOUT:
# 1. fleshing out PcapBlock...
# 2. Adding something to test.db that includes a pcap block?
# 3. if the above looks good, i.e. order of loops.
