from collections.abc import Sequence

import numpy as np
from pydantic import model_validator

from ophyd_async.core import Array1D, StrictEnum, Table


class PandaHdf5DatasetType(StrictEnum):
    """Dataset options for HDF capture."""

    FLOAT_64 = "float64"
    UINT_32 = "uint32"


class DatasetTable(Table):
    name: Sequence[str]
    dtype: Sequence[PandaHdf5DatasetType]


class SeqTrigger(StrictEnum):
    """Trigger options for the SeqTable."""

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


class SeqTable(Table):
    """Data type for the panda seq table."""

    repeats: Array1D[np.uint16]
    trigger: Sequence[SeqTrigger]
    position: Array1D[np.int32]
    time1: Array1D[np.uint32]
    outa1: Array1D[np.bool_]
    outb1: Array1D[np.bool_]
    outc1: Array1D[np.bool_]
    outd1: Array1D[np.bool_]
    oute1: Array1D[np.bool_]
    outf1: Array1D[np.bool_]
    time2: Array1D[np.uint32]
    outa2: Array1D[np.bool_]
    outb2: Array1D[np.bool_]
    outc2: Array1D[np.bool_]
    outd2: Array1D[np.bool_]
    oute2: Array1D[np.bool_]
    outf2: Array1D[np.bool_]

    @staticmethod
    def row(
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
        # Let pydantic do the conversions for us
        return SeqTable(**{k: [v] for k, v in locals().items()})  # type: ignore

    @model_validator(mode="after")
    def _validate_max_length(self) -> "SeqTable":
        # Used to check max_length. Unfortunately trying the ``max_length`` arg in
        # the pydantic field doesn't work.
        first_length = len(self)
        max_length = 4096
        if first_length > max_length:
            msg = f"Length {first_length} is too long"
            raise ValueError(msg)
        return self
