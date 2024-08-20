from enum import Enum
from typing import Annotated, Sequence

import numpy as np
import numpy.typing as npt
from pydantic import Field
from pydantic_numpy.helper.annotation import NpArrayPydanticAnnotation
from typing_extensions import TypedDict

from ophyd_async.epics.signal import PvaTable


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


PydanticNp1DArrayInt32 = Annotated[
    np.ndarray[tuple[int], np.int32],
    NpArrayPydanticAnnotation.factory(
        data_type=np.int32, dimensions=1, strict_data_typing=False
    ),
]
PydanticNp1DArrayBool = Annotated[
    np.ndarray[tuple[int], np.bool_],
    NpArrayPydanticAnnotation.factory(
        data_type=np.bool_, dimensions=1, strict_data_typing=False
    ),
]

PydanticNp1DArrayUnicodeString = Annotated[
    np.ndarray[tuple[int], np.unicode_],
    NpArrayPydanticAnnotation.factory(
        data_type=np.unicode_, dimensions=1, strict_data_typing=False
    ),
]


class SeqTable(PvaTable):
    repeats: PydanticNp1DArrayInt32 = Field(
        default_factory=lambda: np.array([], np.int32)
    )
    trigger: PydanticNp1DArrayUnicodeString = Field(
        default_factory=lambda: np.array([], dtype=np.dtype("<U32"))
    )
    position: PydanticNp1DArrayInt32 = Field(
        default_factory=lambda: np.array([], dtype=np.int32)
    )
    time1: PydanticNp1DArrayInt32 = Field(
        default_factory=lambda: np.array([], dtype=np.int32)
    )
    outa1: PydanticNp1DArrayBool = Field(
        default_factory=lambda: np.array([], dtype=np.bool_)
    )
    outb1: PydanticNp1DArrayBool = Field(
        default_factory=lambda: np.array([], dtype=np.bool_)
    )
    outc1: PydanticNp1DArrayBool = Field(
        default_factory=lambda: np.array([], dtype=np.bool_)
    )
    outd1: PydanticNp1DArrayBool = Field(
        default_factory=lambda: np.array([], dtype=np.bool_)
    )
    oute1: PydanticNp1DArrayBool = Field(
        default_factory=lambda: np.array([], dtype=np.bool_)
    )
    outf1: PydanticNp1DArrayBool = Field(
        default_factory=lambda: np.array([], dtype=np.bool_)
    )
    time2: PydanticNp1DArrayInt32 = Field(
        default_factory=lambda: np.array([], dtype=np.int32)
    )
    outa2: PydanticNp1DArrayBool = Field(
        default_factory=lambda: np.array([], dtype=np.bool_)
    )
    outb2: PydanticNp1DArrayBool = Field(
        default_factory=lambda: np.array([], dtype=np.bool_)
    )
    outc2: PydanticNp1DArrayBool = Field(
        default_factory=lambda: np.array([], dtype=np.bool_)
    )
    outd2: PydanticNp1DArrayBool = Field(
        default_factory=lambda: np.array([], dtype=np.bool_)
    )
    oute2: PydanticNp1DArrayBool = Field(
        default_factory=lambda: np.array([], dtype=np.bool_)
    )
    outf2: PydanticNp1DArrayBool = Field(
        default_factory=lambda: np.array([], dtype=np.bool_)
    )

    @classmethod
    def row(
        cls,
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
    ) -> "SeqTable":
        return PvaTable.row(
            cls,
            repeats=repeats,
            trigger=trigger,
            position=position,
            time1=time1,
            outa1=outa1,
            outb1=outb1,
            outc1=outc1,
            outd1=outd1,
            oute1=oute1,
            outf1=outf1,
            time2=time2,
            outa2=outa2,
            outb2=outb2,
            outc2=outc2,
            outd2=outd2,
            oute2=oute2,
            outf2=outf2,
        )
