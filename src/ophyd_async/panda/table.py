from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence, TypedDict

import numpy as np
import numpy.typing as npt


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


@dataclass
class SeqTableRow:
    repeats: int = 1
    trigger: SeqTrigger = SeqTrigger.IMMEDIATE
    position: int = 0
    time1: int = 0
    outa1: bool = False
    outb1: bool = False
    outc1: bool = False
    outd1: bool = False
    oute1: bool = False
    outf1: bool = False
    time2: int = 0
    outa2: bool = False
    outb2: bool = False
    outc2: bool = False
    outd2: bool = False
    oute2: bool = False
    outf2: bool = False


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


def seq_table_from_rows(*rows: SeqTableRow):
    """
    Constructs a sequence table from a series of rows.
    """
    return seq_table_from_arrays(
        repeats=np.ndarray([row.repeats for row in rows], dtype=np.uint16),
        trigger=[row.trigger for row in rows],
        position=np.ndarray([row.position for row in rows], dtype=np.int32),
        time1=np.ndarray([row.time1 for row in rows], dtype=np.uint32),
        outa1=np.ndarray([row.outa1 for row in rows], dtype=np.bool_),
        outb1=np.ndarray([row.outb1 for row in rows], dtype=np.bool_),
        outc1=np.ndarray([row.outc1 for row in rows], dtype=np.bool_),
        outd1=np.ndarray([row.outd1 for row in rows], dtype=np.bool_),
        oute1=np.ndarray([row.oute1 for row in rows], dtype=np.bool_),
        outf1=np.ndarray([row.outf1 for row in rows], dtype=np.bool_),
        time2=np.ndarray([row.time2 for row in rows], dtype=np.uint32),
        outa2=np.ndarray([row.outa2 for row in rows], dtype=np.bool_),
        outb2=np.ndarray([row.outb2 for row in rows], dtype=np.bool_),
        outc2=np.ndarray([row.outc2 for row in rows], dtype=np.bool_),
        outd2=np.ndarray([row.outd2 for row in rows], dtype=np.bool_),
        oute2=np.ndarray([row.oute2 for row in rows], dtype=np.bool_),
        outf2=np.ndarray([row.outf2 for row in rows], dtype=np.bool_),
    )


def seq_table_from_arrays(
        *,
        repeats: Optional[npt.NDArray[np.uint16]] = None,
        trigger: Optional[Sequence[SeqTrigger]] = None,
        position: Optional[npt.NDArray[np.int32]] = None,
        time1: Optional[npt.NDArray[np.uint32]] = None,
        outa1: Optional[npt.NDArray[np.bool_]] = None,
        outb1: Optional[npt.NDArray[np.bool_]] = None,
        outc1: Optional[npt.NDArray[np.bool_]] = None,
        outd1: Optional[npt.NDArray[np.bool_]] = None,
        oute1: Optional[npt.NDArray[np.bool_]] = None,
        outf1: Optional[npt.NDArray[np.bool_]] = None,
        time2: npt.NDArray[np.uint32],
        outa2: Optional[npt.NDArray[np.bool_]] = None,
        outb2: Optional[npt.NDArray[np.bool_]] = None,
        outc2: Optional[npt.NDArray[np.bool_]] = None,
        outd2: Optional[npt.NDArray[np.bool_]] = None,
        oute2: Optional[npt.NDArray[np.bool_]] = None,
        outf2: Optional[npt.NDArray[np.bool_]] = None,
) -> SeqTable:
    """
    Constructs a sequence table from a series of columns as arrays.
    time2 is the only required argument and must not be None.
    All other provided arguments must be of equal length to time2.
    If any other argument is not given, or else given as None or empty,
    an array of length len(time2) filled with the following is defaulted:
    repeats: 1
    trigger: SeqTrigger.IMMEDIATE
    all others: 0/False as appropriate
    """
    assert time2 is not None, "time2 must be provided"
    length = len(time2)
    assert 0 < length < 4096, f"Length {length} not in range"

    def is_invalid(value: Optional[npt.NDArray]):
        if value is None or len(value) == 0:
            return True
        return False

    table = SeqTable(
        repeats=np.ones(length) if is_invalid(repeats) else repeats,
        trigger=trigger or [SeqTrigger.IMMEDIATE] * length,
        position=np.zeros(length) if is_invalid(position) else position,
        time1=np.zeros(length) if is_invalid(time1) else time1,
        outa1=np.zeros(length) if is_invalid(outa1) else outa1,
        outb1=np.zeros(length) if is_invalid(outb1) else outb1,
        outc1=np.zeros(length) if is_invalid(outc1) else outc1,
        outd1=np.zeros(length) if is_invalid(outd1) else outd1,
        oute1=np.zeros(length) if is_invalid(oute1) else oute1,
        outf1=np.zeros(length) if is_invalid(outf1) else outf1,
        time2=time2,
        outa2=np.zeros(length) if is_invalid(outa2) else outa2,
        outb2=np.zeros(length) if is_invalid(outb2) else outb2,
        outc2=np.zeros(length) if is_invalid(outc2) else outc2,
        outd2=np.zeros(length) if is_invalid(outd2) else outd2,
        oute2=np.zeros(length) if is_invalid(oute2) else oute2,
        outf2=np.zeros(length) if is_invalid(outf2) else outf2,
    )
    for k, v in table.items():
        if len(v) != length:
            raise ValueError(f"{k}: has length {len(v)} not {length}")
    return table
