from __future__ import annotations

import re
from typing import (
    Callable,
    Dict,
    FrozenSet,
    Optional,
    Tuple,
    Type,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from p4p.client.thread import Context

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    Device,
    DeviceVector,
    Signal,
    SignalBackend,
    SignalR,
    SignalRW,
    SignalX,
    SimSignalBackend,
)
from ophyd_async.epics.pvi import PVIEntry, make_signal, pvi_get
from ophyd_async.panda.table import SeqTable
from ophyd_async.panda.utils import PVIEntry


class PulseBlock(Device):
    delay: SignalRW[float]
    width: SignalRW[float]


class SeqBlock(Device):
    table: SignalRW[SeqTable]
    active: SignalRW[bool]


class PcapBlock(Device):
    active: SignalR[bool]
    arm: SignalRW[bool]


def _block_name_number(block_name: str) -> Tuple[str, Optional[int]]:
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


def _remove_inconsistent_blocks(pvi_info: Optional[Dict[str, PVIEntry]]) -> None:
    """Remove blocks from pvi information.

    This is needed because some pandas have 'pcap' and 'pcap1' blocks, which are
    inconsistent with the assumption that pandas should only have a 'pcap' block,
    for example.

    """
    if pvi_info is None:
        return
    pvi_keys = set(pvi_info.keys())
    for k in pvi_keys:
        kn = re.sub(r"\d*$", "", k)
        if kn and k != kn and kn in pvi_keys:
            del pvi_info[k]


class PandA(Device):
    pulse: DeviceVector[PulseBlock]
    seq: DeviceVector[SeqBlock]
    pcap: PcapBlock

    def __init__(self, prefix: str, name: str = "") -> None:
        super().__init__(name)
        self._prefix = prefix

    def verify_block(self, name: str, num: Optional[int]):
        """Given a block name and number, return information about a block."""
        anno = get_type_hints(self, globalns=globals()).get(name)

        block: Device = Device()

        if anno:
            type_args = get_args(anno)
            block = type_args[0]() if type_args else anno()

            if not type_args:
                assert num is None, f"Only expected one {name} block, got {num}"

        return block

    async def _make_block(
        self,
        name: str,
        num: Optional[int],
        block_pv: str,
        sim: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """Makes a block given a block name containing relevant signals.

        Loops through the signals in the block (found using type hints), if not in
        sim mode then does a pvi call, and identifies this signal from the pvi call.
        """
        block = self.verify_block(name, num)

        field_annos = get_type_hints(block, globalns=globals())
        block_pvi = await pvi_get(block_pv, timeout=timeout) if not sim else None

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

                signal: Signal = make_signal(entry, args[0] if len(args) > 0 else None)

            else:
                backend: SignalBackend = SimSignalBackend(
                    args[0] if len(args) > 0 else None, block_pv
                )
                signal = SignalX(backend) if not origin else origin(backend)

            setattr(block, sig_name, signal)

        # checks for any extra pvi information not contained in this class
        if block_pvi:
            for attr, attr_pvi in block_pvi.items():
                if not hasattr(block, attr):
                    # makes any extra signals
                    setattr(block, attr, make_signal(attr_pvi))

        return block

    async def _make_untyped_block(
        self, block_pv: str, timeout: float = DEFAULT_TIMEOUT
    ):
        """Populates a block using PVI information.

        This block is not typed as part of the PandA interface but needs to be
        included dynamically anyway.
        """
        block = Device()
        block_pvi: Dict[str, PVIEntry] = await pvi_get(block_pv, timeout=timeout)

        for signal_name, signal_pvi in block_pvi.items():
            setattr(block, signal_name, make_signal(signal_pvi))

        return block

    # TODO redo to set_panda_block? confusing name
    def set_attribute(self, name: str, num: Optional[int], block: Device):
        """Set a block on the panda.

        Need to be able to set device vectors on the panda as well, e.g. if num is not
        None, need to be able to make a new device vector and start populating it...
        """
        anno = get_type_hints(self, globalns=globals()).get(name)

        # if it's an annotated device vector, or it isn't but we've got a number then
        # make a DeviceVector on the class
        if get_origin(anno) == DeviceVector or (not anno and num is not None):
            self.__dict__.setdefault(name, DeviceVector())[num] = block
        else:
            setattr(self, name, block)

    async def connect(
        self, sim: bool = False, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        """Initialises all blocks and connects them.

        First, checks for pvi information. If it exists, make all blocks from this.
        Then, checks that all required blocks in the PandA have been made.

        If there's no pvi information, that's because we're in sim mode. In that case,
        makes all required blocks.
        """
        pvi_info = (
            await pvi_get(self._prefix + "PVI", timeout=timeout) if not sim else None
        )
        _remove_inconsistent_blocks(pvi_info)

        hints = {
            attr_name: attr_type
            for attr_name, attr_type in get_type_hints(self, globalns=globals()).items()
            if not attr_name.startswith("_")
        }

        # create all the blocks pvi says it should have,
        if pvi_info:
            pvi_info = cast(Dict[str, PVIEntry], pvi_info)
            for block_name, block_pvi in pvi_info.items():
                name, num = _block_name_number(block_name)

                if name in hints:
                    block = await self._make_block(
                        name, num, block_pvi["d"], timeout=timeout
                    )
                else:
                    block = await self._make_untyped_block(
                        block_pvi["d"], timeout=timeout
                    )

                self.set_attribute(name, num, block)

        # then check if the ones defined in this class are in the pvi info
        # make them if there is no pvi info, i.e. sim mode.
        for block_name in hints.keys():
            if pvi_info is not None:
                pvi_name = block_name

                if get_origin(hints[block_name]) == DeviceVector:
                    pvi_name += "1"

                entry: Optional[PVIEntry] = pvi_info.get(pvi_name)

                assert entry, f"Expected PandA to contain {block_name} block."
                assert list(entry) == [
                    "d"
                ], f"Expected PandA to only contain blocks, got {entry}"
            else:
                num = 1 if get_origin(hints[block_name]) == DeviceVector else None
                block = await self._make_block(
                    block_name, num, "sim://", sim=sim, timeout=timeout
                )
                self.set_attribute(block_name, num, block)

        self.set_name(self.name)
        await super().connect(sim)
