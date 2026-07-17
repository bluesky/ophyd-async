from collections.abc import Sequence
from pathlib import Path
from typing import Annotated as A

import numpy as np

from ophyd_async.core import (
    Array1D,
    SignalR,
    SignalRW,
    SignalW,
    StrictEnum,
    SubsetEnum,
    SupersetEnum,
    Table,
    TriggerableCommand,
)
from ophyd_async.epics.core import (
    EpicsDevice,
    PvSuffix,
)

CA_PVA_RECORDS = Path(__file__).parent / "_epics_test_ca_records.db"
PVA_RECORDS = Path(__file__).parent / "_epics_test_pva_records.db"


class EpicsTestEnum(StrictEnum):
    """For testing strict enum values in test IOCs."""

    A = "Aaa"
    B = "Bbb"
    C = "Ccc"


class EpicsTestSubsetEnum(SubsetEnum):
    """For testing subset enum values in test IOCs.

    The backing PV (mbbo with choices Aaa/Bbb/Ccc) has an extra choice ("Ccc")
    beyond what this enum declares.
    """

    A = "Aaa"
    B = "Bbb"


class EpicsTestSupersetEnum(SupersetEnum):
    """For testing superset enum values in test IOCs.

    Deliberately points at the same backing PV as `EpicsTestSubsetEnum`
    (mbbo with choices Aaa/Bbb/Ccc): this enum declares a choice ("Ddd") that
    does not exist in the backend, which is exactly what a superset enum
    allows.
    """

    A = "Aaa"
    B = "Bbb"
    C = "Ccc"
    D = "Ddd"


class EpicsTestTable(Table):
    a_bool: Array1D[np.bool_]
    a_int: Array1D[np.int32]
    a_float: Array1D[np.float64]
    a_str: Sequence[str]
    a_enum: Sequence[EpicsTestEnum]


class EpicsTestCaDevice(EpicsDevice):
    """Device for use in a channel access test IOC."""

    a_int: A[SignalRW[int], PvSuffix("int")]
    """A thing"""
    a_float: A[SignalRW[float], PvSuffix("float")]
    float_prec_0: A[SignalRW[int], PvSuffix("float_prec_0")]
    a_str: A[SignalRW[str], PvSuffix("str")]
    longstr: A[SignalRW[str], PvSuffix("longstr")]
    longstr2: A[SignalRW[str], PvSuffix("longstr2.VAL$")]
    a_bool: A[SignalRW[bool], PvSuffix("bool")]
    slowseq: A[SignalRW[int], PvSuffix("slowseq")]
    enum: A[SignalRW[EpicsTestEnum], PvSuffix("enum")]
    enum2: A[SignalRW[EpicsTestEnum], PvSuffix("enum2")]
    subset_enum: A[SignalRW[EpicsTestSubsetEnum], PvSuffix("subset_enum")]
    superset_enum: A[SignalRW[EpicsTestSupersetEnum], PvSuffix("subset_enum")]
    enum_str_fallback: A[SignalRW[str], PvSuffix("enum_str_fallback")]
    bool_unnamed: A[SignalRW[bool], PvSuffix("bool_unnamed")]
    partialint: A[SignalRW[int], PvSuffix("partialint")]
    lessint: A[SignalRW[int], PvSuffix("lessint")]
    uint8a: A[SignalRW[Array1D[np.uint8]], PvSuffix("uint8a")]
    int16a: A[SignalRW[Array1D[np.int16]], PvSuffix("int16a")]
    int32a: A[SignalRW[Array1D[np.int32]], PvSuffix("int32a")]
    float32a: A[SignalRW[Array1D[np.float32]], PvSuffix("float32a")]
    float64a: A[SignalRW[Array1D[np.float64]], PvSuffix("float64a")]
    stra: A[SignalRW[Sequence[str]], PvSuffix("stra")]
    mbb_direct_bit_r: A[SignalR[bool], PvSuffix("mbb_direct.B0")]
    mbb_direct_bit: A[SignalRW[bool], PvSuffix("mbb_direct_rw.B0")]
    go: A[TriggerableCommand, PvSuffix("go")]


class EpicsTestPvaDevice(EpicsTestCaDevice):
    """Device for use in a pv access test IOC."""

    # pva can support all signal types that ca can
    int8a: A[SignalRW[Array1D[np.int8]], PvSuffix("int8a")]
    uint16a: A[SignalRW[Array1D[np.uint16]], PvSuffix("uint16a")]
    uint32a: A[SignalRW[Array1D[np.uint32]], PvSuffix("uint32a")]
    int64a: A[SignalRW[Array1D[np.int64]], PvSuffix("int64a")]
    uint64a: A[SignalRW[Array1D[np.uint64]], PvSuffix("uint64a")]
    table: A[SignalRW[EpicsTestTable], PvSuffix("table")]
    ntndarray: A[SignalR[np.ndarray], PvSuffix("ntndarray")]


class EpicsTestPviDevice(EpicsDevice):
    """Device for use in a generic PVI test IOC, independent of PandA/FastCS.

    Construct with `with_pvi=True`: signals here are plain type annotations
    with no `PvSuffix`, discovered and filled in from the IOC's PVI structure
    by `PviDeviceConnector` at connect time.

    Most fields (`mbb_direct_bit_r`, `a_float`, `table`, `ntndarray`, `go`)
    reuse the same attribute names, PVI entries and backing records as
    `EpicsTestCaDevice`/`EpicsTestPvaDevice`, rather than declaring new
    synthetic ones. Only `wo_float` is bespoke to this device, as no
    write-only field exists on those devices to reuse.
    """

    mbb_direct_bit_r: SignalR[bool]
    a_float: SignalRW[float]
    wo_float: SignalW[float]
    table: SignalRW[EpicsTestTable]
    ntndarray: SignalR[np.ndarray]
    go: TriggerableCommand


class EpicsTestPviDisagreeingSuffixDevice(EpicsDevice):
    """Device whose `PvSuffix` contradicts the PVI structure serving it.

    `overridden_float` is annotated at the `float_prec_1` record, but the IOC's
    PVI directory points it at the same record as `a_float`. Two different PVs
    for one Signal means one of them is wrong, so connecting must raise rather
    than silently pick either. Construct with `with_pvi=True`.

    It is a device of its own because it cannot connect: a disagreeing Signal
    would otherwise stop `EpicsTestPviDevice` connecting at all.
    """

    overridden_float: A[SignalRW[float], PvSuffix("float_prec_1")]
