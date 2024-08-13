from enum import Enum
from typing import NotRequired, Sequence

import numpy as np
import numpy.typing as npt
import pydantic_numpy as pnd
from typing_extensions import TypedDict


class PandaHdf5DatasetType(str, Enum):
    FLOAT_64 = "float64"
    UINT_32 = "uint32"


class DatasetTable(TypedDict):
    name: npt.NDArray[np.str_]
    hdf5_type: Sequence[PandaHdf5DatasetType]


class SeqTrigger(str, Enum):
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


SeqTableRowType = np.dtype(
    [
        ("repeats", np.int32),
        ("trigger", "U14"),  # One of the SeqTrigger values
        ("position", np.int32),
        ("time1", np.int32),
        ("outa1", np.bool_),
        ("outb1", np.bool_),
        ("outc1", np.bool_),
        ("outd1", np.bool_),
        ("oute1", np.bool_),
        ("outf1", np.bool_),
        ("time2", np.int32),
        ("outa2", np.bool_),
        ("outb2", np.bool_),
        ("outc2", np.bool_),
        ("outd2", np.bool_),
        ("oute2", np.bool_),
        ("outf2", np.bool_),
    ]
)


def seq_table_row(
    *,
    repeats: int = 0,
    trigger: str = "",
    position: int = 0,
    time1: int = 0,
    outa1: bool = False,
    outb1: bool = False,
    outc1: bool = False,
    outd1: bool = False,
    oute1: bool = False,
    outf1: bool = False,
    time2: int = 0,
    outa2: bool = False,
    outb2: bool = False,
    outc2: bool = False,
    outd2: bool = False,
    oute2: bool = False,
    outf2: bool = False,
) -> pnd.NpNDArray:
    return np.array(
        (
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
        ),
        dtype=SeqTableRowType,
    )


_SEQ_TABLE_ROW_SHAPE = seq_table_row().shape
_SEQ_TABLE_COLUMN_NAMES = [x[0] for x in SeqTableRowType.names]


def create_seq_table(*rows: pnd.NpNDArray) -> pnd.NpNDArray:
    if not (0 < len(rows) < 4096):
        raise ValueError(f"Length {len(rows)} not in range.")

    if not all(isinstance(row, np.ndarray) for row in rows):
        for row in rows:
            if not isinstance(row, np.void):
                raise ValueError(
                    f"Cannot construct a SeqTable, some rows {row} are not arrays {type(row)}."
                )
        raise ValueError("Cannot construct a SeqTable, some rows are not arrays.")
    if not all(row.shape == _SEQ_TABLE_ROW_SHAPE for row in rows):
        raise ValueError(
            "Cannot construct a SeqTable, some rows have incorrect shapes."
        )
    if not all(row.dtype is SeqTableRowType for row in rows):
        raise ValueError("Cannot construct a SeqTable, some rows have incorrect types.")

    return np.array(rows)


class SeqTablePvaTable(TypedDict):
    repeats: NotRequired[pnd.Np1DArrayUint16]
    trigger: NotRequired[Sequence[SeqTrigger]]
    position: NotRequired[pnd.Np1DArrayInt32]
    time1: NotRequired[pnd.Np1DArrayUint32]
    outa1: NotRequired[pnd.Np1DArrayBool]
    outb1: NotRequired[pnd.Np1DArrayBool]
    outc1: NotRequired[pnd.Np1DArrayBool]
    outd1: NotRequired[pnd.Np1DArrayBool]
    oute1: NotRequired[pnd.Np1DArrayBool]
    outf1: NotRequired[pnd.Np1DArrayBool]
    time2: NotRequired[pnd.Np1DArrayUint32]
    outa2: NotRequired[pnd.Np1DArrayBool]
    outb2: NotRequired[pnd.Np1DArrayBool]
    outc2: NotRequired[pnd.Np1DArrayBool]
    outd2: NotRequired[pnd.Np1DArrayBool]
    oute2: NotRequired[pnd.Np1DArrayBool]
    outf2: NotRequired[pnd.Np1DArrayBool]


def convert_seq_table_to_columnwise_pva_table(
    seq_table: pnd.NpNDArray,
) -> SeqTablePvaTable:
    if seq_table.dtype != SeqTableRowType:
        raise ValueError(
            f"Cannot convert a SeqTable to a columnwise dictionary, "
            f"input is not a SeqTable {seq_table.dtype}."
        )
    print(seq_table)
    transposed = seq_table.transpose(axis=1)
    return dict(zip(_SEQ_TABLE_COLUMN_NAMES, transposed))
