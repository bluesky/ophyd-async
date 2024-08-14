from enum import Enum
from typing import Dict, Sequence, Union

import numpy as np
import numpy.typing as npt
import pydantic_numpy as pnd
from pydantic import Field, RootModel, field_validator
from typing_extensions import TypedDict

from ophyd_async.epics.signal import PvaTableAbstraction


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




class SeqTable(RootModel, PvaTableAbstraction):
    root: pnd.NpNDArray = Field(
        default_factory=lambda: np.array([], dtype=SeqTableRowType),
    )

    def convert_to_protocol_datatype(self) -> Dict[str, npt.ArrayLike]:
        """Convert root to the column-wise dict representation for backend put"""

        if len(self.root) == 0:
            transposed = {  # list with empty arrays, each with correct dtype
                name: np.array([], dtype=dtype) for name, dtype in SeqTableRowType.descr
            }
        else:
            transposed_list = list(zip(*list(self.root)))
            transposed = {
                name: np.array(col, dtype=dtype)
                for col, (name, dtype) in zip(transposed_list, SeqTableRowType.descr)
            }
        return transposed

    @classmethod
    def convert_from_protocol_datatype(
        cls, pva_table: Dict[str, npt.ArrayLike]
    ) -> "SeqTable":
        """Convert a pva table to a row-wise SeqTable."""

        ordered_columns = [
            np.array(pva_table[name], dtype=dtype)
            for name, dtype in SeqTableRowType.descr
        ]

        transposed = list(zip(*ordered_columns))
        rows = np.array([tuple(row) for row in transposed], dtype=SeqTableRowType)
        return cls(rows)

    @field_validator("root", mode="before")
    @classmethod
    def check_valid_rows(cls, rows: Union[Sequence, np.ndarray]):
        assert isinstance(
            rows, (np.ndarray, list)
        ), "Rows must be a list or numpy array."

        if not (0 <= len(rows) < 4096):
            raise ValueError(f"Length {len(rows)} not in range.")

        if not all(isinstance(row, (np.ndarray, np.void)) for row in rows):
            raise ValueError(
                "Cannot construct a SeqTable, some rows are not arrays."
            )

        if not all(row.dtype is SeqTableRowType for row in rows):
            raise ValueError(
                "Cannot construct a SeqTable, some rows have incorrect types."
            )

        return np.array(rows, dtype=SeqTableRowType)
