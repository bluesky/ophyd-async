from collections import deque, namedtuple
from typing import Iterable, List

import numpy as np
from ophyd_async.panda import SeqTable, SeqTrigger

Frame = namedtuple(
    "Frame",
    (
        "repeats",
        "trigger",
        "position",
        "time1",
        "outa1",
        "outb1",
        "outc1",
        "outd1",
        "oute1",
        "outf1",
        "time2",
        "outa2",
        "outb2",
        "outc2",
        "outd2",
        "oute2",
        "outf2",
    ),
)


def frame(
    *,
    repeats: int = 1,
    trigger: SeqTrigger = SeqTrigger.IMMEDIATE,
    position: int = 0,
    time1: int = 0,
    outa1: bool = 0,
    outb1: bool = 0,
    outc1: bool = 0,
    outd1: bool = 0,
    oute1: bool = 0,
    outf1: bool = 0,
    time2: int = 0,
    outa2: bool = 0,
    outb2: bool = 0,
    outc2: bool = 0,
    outd2: bool = 0,
    oute2: bool = 0,
    outf2: bool = 0,
) -> Frame:
    """Create frame optionally overriding default values"""    
    return Frame(
        repeats,
        trigger,
        position,
        time1,
        outa1,
        outb1,
        outc1,
        outd1,
        oute1,
        outf1,
        time2,
        outa2,
        outb2,
        outc2,
        outd2,
        oute2,
        outf2,
    )


def table_chunks(frames: Iterable[Frame], length: int) -> Iterable[List[Frame]]:
    """Split stream of frames into groups that can be set as sequence tables"""
    buffer = [iter(frames)] * length
    for chunk in zip(*buffer):
        yield list(chunk) + [frame(repeats=0)]


def seq_tables(tables: Iterable[Iterable[Frame]]) -> Iterable[SeqTable]:
    for table in tables:
        yield build_table(*zip(*table))


def build_table(
    repeats: Iterable[int],
    trigger: Iterable[SeqTrigger] ,
    position: Iterable[int],
    time1: Iterable[int],
    outa1: Iterable[bool],
    outb1: Iterable[bool],
    outc1: Iterable[bool],
    outd1: Iterable[bool],
    oute1: Iterable[bool],
    outf1: Iterable[bool],
    time2: Iterable[int],
    outa2: Iterable[bool],
    outb2: Iterable[bool],
    outc2: Iterable[bool],
    outd2: Iterable[bool],
    oute2: Iterable[bool],
    outf2: Iterable[bool],
) -> SeqTable:
    table = SeqTable()
    table["repeats"] = np.array(repeats, np.uint16)
    table["position"] = np.array(position, np.int32)
    table["trigger"] = np.array(trigger, SeqTable)
    table["time1"] = np.array(time1, np.uint32)
    table["outa1"] = np.array(outa1, np.uint8)
    table["outb1"] = np.array(outb1, np.uint8)
    table["outc1"] = np.array(outc1, np.uint8)
    table["outd1"] = np.array(outd1, np.uint8)
    table["oute1"] = np.array(oute1, np.uint8)
    table["outf1"] = np.array(outf1, np.uint8)
    table["time2"] = np.array(time2, np.uint32)
    table["outa2"] = np.array(outa2, np.uint8)
    table["outb2"] = np.array(outb2, np.uint8)
    table["outc2"] = np.array(outc2, np.uint8)
    table["outd2"] = np.array(outd2, np.uint8)
    table["oute2"] = np.array(oute2, np.uint8)
    table["outf2"] = np.array(outf2, np.uint8)
    return table
