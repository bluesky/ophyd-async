import atexit
import re
from enum import Enum
from typing import (
    Callable,
    Dict,
    FrozenSet,
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
    DeviceVector,
    Signal,
    SignalRW,
    SignalX,
    SimSignalBackend,
)
from ophyd.v2.epics import (
    SignalR,
    epics_signal_r,
    epics_signal_rw,
    epics_signal_w,
    epics_signal_x,
)
from p4p.client.thread import Context


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
    active: SignalR[bool]


class PVIEntry(TypedDict, total=False):
    d: str
    r: str
    rw: str
    w: str
    x: str


def block_name_number(block_name: str) -> Tuple[str, Optional[int]]:
    """Maps a panda block name to a block and number.

    There are exceptions to this rule; some blocks like pcap do not contain numbers.
    Other blocks may contain numbers and letters, but no numbers at the end.

    Such block names will only return the block name, and not a number.

    If this function returns both a block name and number, it should be instantiated
    into a device vector."""
    m = re.match("^([0-9a-z_-]*)([0-9]+)$", block_name)
    if m is not None:
        name, num = m.groups()
        return name, int(num or 1)  # just to pass type checks.

    return block_name, None


async def pvi_get(pv: str, ctxt: Context, timeout: float = 5.0) -> Dict[str, PVIEntry]:
    pv_info = ctxt.get(pv, timeout=timeout).get("pvi").todict()

    result = {}

    for attr_name, attr_info in pv_info.items():
        result[attr_name] = PVIEntry(**attr_info)  # type: ignore
    return result


class PandA(Device):
    _ctxt: Optional[Context] = None

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

    @property
    def ctxt(self) -> Context:
        if PandA._ctxt is None:
            PandA._ctxt = Context("pva", nt=False)

            @atexit.register
            def _del_ctxt():
                # If we don't do this we get messages like this on close:
                #   Error in sys.excepthook:
                #   Original exception was:
                PandA._ctxt = None

        return PandA._ctxt

    def verify_block(self, name: str, num: Optional[int]):
        """Given a block name and number, return information about a block."""
        anno = get_type_hints(self).get(name)

        block: Device = Device()

        if anno:
            type_args = get_args(anno)
            block = type_args[0]() if type_args else anno()

            if not type_args:
                assert num is None, f"Only expected one {name} block, got {num}"

        return block

    async def _make_block(
        self, name: str, num: Optional[int], block_pv: str, sim: bool = False
    ):
        """Makes a block given a block name containing relevant signals.

        Loops through the signals in the block (found using type hints), if not in
        sim mode then does a pvi call, and identifies this signal from the pvi call.
        """
        block = self.verify_block(name, num)

        field_annos = get_type_hints(block)
        block_pvi = await pvi_get(block_pv, self.ctxt) if not sim else None

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
                        f"{self.__class__.__name__} has a {name} block containing a/"
                        + f"an {sig_name} signal which has not been retrieved by PVI."
                    )

                signal = self._make_signal(entry, args[0] if len(args) > 0 else None)

            else:
                backend = SimSignalBackend(args[0] if len(args) > 0 else None, block_pv)
                signal = SignalX(backend) if not origin else origin(backend)

            setattr(block, sig_name, signal)

        # checks for any extra pvi information not contained in this class
        if block_pvi:
            for attr, attr_pvi in block_pvi.items():
                if not hasattr(block, attr):
                    # makes any extra signals
                    signal = self._make_signal(attr_pvi)
                    setattr(block, attr, signal)

        return block

    async def _make_untyped_block(self, block_pv: str):
        """Populates a block using PVI information.

        This block is not typed as part of the PandA interface but needs to be
        included dynamically anyway.
        """
        block = Device()
        block_pvi = await pvi_get(block_pv, self.ctxt)

        for signal_name, signal_pvi in block_pvi.items():
            signal = self._make_signal(signal_pvi)
            setattr(block, signal_name, signal)

        return block

    def _make_signal(self, signal_pvi: PVIEntry, dtype: Optional[Type] = None):
        """Make a signal.

        This assumes datatype is None so it can be used to create dynamic signals.
        """
        operations = frozenset(signal_pvi.keys())
        pvs = [signal_pvi[i] for i in operations]  # type: ignore
        signal_factory = self.pvi_mapping[operations]

        write_pv = pvs[0]
        read_pv = write_pv if len(pvs) == 1 else pvs[1]

        return signal_factory(dtype, "pva://" + read_pv, "pva://" + write_pv)

    # TODO redo to set_panda_block? confusing name
    def set_attribute(self, name: str, num: Optional[int], block: Device):
        """Set a block on the panda.

        Need to be able to set device vectors on the panda as well, e.g. if num is not
        None, need to be able to make a new device vector and start populating it...
        """
        anno = get_type_hints(self).get(name)

        # TODO this should not check specifically for pulse or seq block... just that
        # it's a device vector.

        # if it's an annotated device vector, or it isn't but we've got a number then
        # make a DeviceVector on the class
        if get_origin(anno) == DeviceVector or (not anno and num is not None):
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
        pvi = await pvi_get(self._init_prefix + ":PVI", self.ctxt) if not sim else None
        hints = {
            attr_name: attr_type
            for attr_name, attr_type in get_type_hints(self).items()
            if not attr_name.startswith("_")
        }

        # Remove 'fake' numbered blocks if non-numbered block is in PVI, e.g. if
        #   both 'pcap' and 'pcap1' are in PVI, remove 'pcap1'.
        pvi_keys = set(pvi.keys())
        for k in pvi_keys:
            kn = re.sub("\d*$", "", k)
            if kn and k != kn and kn in pvi_keys:
                del pvi[k]

        # create all the blocks pvi says it should have,
        if pvi:
            for block_name, block_pvi in pvi.items():
                name, num = block_name_number(block_name)

                if name in hints:
                    block = await self._make_block(name, num, block_pvi["d"])
                else:
                    block = await self._make_untyped_block(block_pvi["d"])

                self.set_attribute(name, num, block)

        # then check if the ones defined in this class are in the pvi info
        # make them if there is no pvi info, i.e. sim mode.
        for block_name in hints.keys():
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
                num = 1 if get_origin(hints[block_name]) == DeviceVector else None
                block = await self._make_block(block_name, num, "sim://", sim=sim)
                self.set_attribute(block_name, num, block)

        self.set_name(self.name)
        await super().connect(sim)
