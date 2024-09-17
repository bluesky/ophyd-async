from collections.abc import Sequence
from enum import Enum
from typing import Annotated

import numpy as np
import numpy.typing as npt
from pydantic import Field, field_validator, model_validator
from pydantic_numpy.helper.annotation import NpArrayPydanticAnnotation
from typing_extensions import TypedDict

from ophyd_async.core import Table


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
    np.ndarray[tuple[int], np.dtype[np.int32]],
    NpArrayPydanticAnnotation.factory(
        data_type=np.int32, dimensions=1, strict_data_typing=False
    ),
    Field(default_factory=lambda: np.array([], np.int32)),
]
PydanticNp1DArrayBool = Annotated[
    np.ndarray[tuple[int], np.dtype[np.bool_]],
    NpArrayPydanticAnnotation.factory(
        data_type=np.bool_, dimensions=1, strict_data_typing=False
    ),
    Field(default_factory=lambda: np.array([], dtype=np.bool_)),
]
TriggerStr = Annotated[
    np.ndarray[tuple[int], np.dtype[np.unicode_]],
    NpArrayPydanticAnnotation.factory(
        data_type=np.unicode_, dimensions=1, strict_data_typing=False
    ),
    Field(default_factory=lambda: np.array([], dtype=np.dtype("<U32"))),
]


class SeqTable(Table):
    repeats: PydanticNp1DArrayInt32
    trigger: TriggerStr
    position: PydanticNp1DArrayInt32
    time1: PydanticNp1DArrayInt32
    outa1: PydanticNp1DArrayBool
    outb1: PydanticNp1DArrayBool
    outc1: PydanticNp1DArrayBool
    outd1: PydanticNp1DArrayBool
    oute1: PydanticNp1DArrayBool
    outf1: PydanticNp1DArrayBool
    time2: PydanticNp1DArrayInt32
    outa2: PydanticNp1DArrayBool
    outb2: PydanticNp1DArrayBool
    outc2: PydanticNp1DArrayBool
    outd2: PydanticNp1DArrayBool
    oute2: PydanticNp1DArrayBool
    outf2: PydanticNp1DArrayBool

    @classmethod
    def row(  # type: ignore
        cls,
        *,
        repeats: int = 1,
        trigger: str = SeqTrigger.IMMEDIATE,
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
        if isinstance(trigger, SeqTrigger):
            trigger = trigger.value
        return super().row(**locals())

    @field_validator("trigger", mode="before")
    @classmethod
    def trigger_to_np_array(cls, trigger_column):
        """
        The user can provide a list of SeqTrigger enum elements instead of a numpy str.
        """
        if isinstance(trigger_column, Sequence) and all(
            isinstance(trigger, SeqTrigger) for trigger in trigger_column
        ):
            trigger_column = np.array(
                [trigger.value for trigger in trigger_column], dtype=np.dtype("<U32")
            )
        elif isinstance(trigger_column, Sequence) or isinstance(
            trigger_column, np.ndarray
        ):
            for trigger in trigger_column:
                SeqTrigger(
                    trigger
                )  # To check all the given strings are actually `SeqTrigger`s
        else:
            raise ValueError(
                "Expected a numpy array or a sequence of `SeqTrigger`, got "
                f"{type(trigger_column)}."
            )
        return trigger_column

    @model_validator(mode="after")
    def validate_max_length(self) -> "SeqTable":
        """
        Used to check max_length. Unfortunately trying the `max_length` arg in
        the pydantic field doesn't work
        """

        first_length = len(next(iter(self))[1])
        assert 0 <= first_length < 4096, f"Length {first_length} not in range."
        return self
