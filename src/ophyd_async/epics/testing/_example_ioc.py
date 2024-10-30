from collections.abc import Sequence
from pathlib import Path
from typing import Annotated as A
from typing import Literal

import numpy as np

from ophyd_async.core import (
    Array1D,
    SignalRW,
    StrictEnum,
    Table,
)
from ophyd_async.epics.core import (
    EpicsDevice,
    PvSuffix,
)

from ._utils import Template, create_ioc_fixture

CA_PVA_RECORDS = str(Path(__file__).parent / "test_records.db")
PVA_RECORDS = str(Path(__file__).parent / "test_records_pva.db")


class ExampleEnum(StrictEnum):
    a = "Aaa"
    b = "Bbb"
    c = "Ccc"


class ExampleTable(Table):
    bool: Array1D[np.bool_]
    int: Array1D[np.int32]
    float: Array1D[np.float64]
    str: Sequence[str]
    enum: Sequence[ExampleEnum]


class CaAndPvaDevice(EpicsDevice):
    my_int: A[SignalRW[int], PvSuffix("int")]
    my_float: A[SignalRW[float], PvSuffix("float")]
    my_str: A[SignalRW[str], PvSuffix("str")]
    my_bool: A[SignalRW[bool], PvSuffix("bool")]
    enum: A[SignalRW[ExampleEnum], PvSuffix("enum")]
    enum2: A[SignalRW[ExampleEnum], PvSuffix("enum2")]
    bool_unnamed: A[SignalRW[bool], PvSuffix("bool_unnamed")]
    partialint: A[SignalRW[int], PvSuffix("partialint")]
    lessint: A[SignalRW[int], PvSuffix("lessint")]
    uint8a: A[SignalRW[Array1D[np.uint8]], PvSuffix("uint8a")]
    int16a: A[SignalRW[Array1D[np.int16]], PvSuffix("int16a")]
    int32a: A[SignalRW[Array1D[np.int32]], PvSuffix("int32a")]
    float32a: A[SignalRW[Array1D[np.float32]], PvSuffix("float32a")]
    float64a: A[SignalRW[Array1D[np.float64]], PvSuffix("float64a")]
    stra: A[SignalRW[Sequence[str]], PvSuffix("stra")]


class PvaDevice(CaAndPvaDevice):
    int8a: A[SignalRW[Array1D[np.int8]], PvSuffix("int8a")]
    uint16a: A[SignalRW[Array1D[np.uint16]], PvSuffix("uint16a")]
    uint32a: A[SignalRW[Array1D[np.uint32]], PvSuffix("uint32a")]
    int64a: A[SignalRW[Array1D[np.int64]], PvSuffix("int64a")]
    uint64a: A[SignalRW[Array1D[np.uint64]], PvSuffix("uint64a")]
    table: A[SignalRW[ExampleTable], PvSuffix("table")]
    ntndarray_data: A[SignalRW[Array1D[np.int64]], PvSuffix("ntndarray:data")]


async def connect_example_device(prefix: str, protocol: Literal["ca", "pva"]):
    device_cls = PvaDevice if protocol == "pva" else CaAndPvaDevice
    device = device_cls(f"{protocol}://{prefix}")
    await device.connect()
    return device


def create_example_ioc_fixture(prefix: str):
    return create_ioc_fixture(
        Template(CA_PVA_RECORDS, f"P={prefix}"),
        Template(PVA_RECORDS, f"P={prefix}"),
    )
