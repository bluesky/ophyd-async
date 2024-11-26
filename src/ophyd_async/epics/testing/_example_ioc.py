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

from ._utils import TestingIOC

CA_PVA_RECORDS = str(Path(__file__).parent / "test_records.db")
PVA_RECORDS = str(Path(__file__).parent / "test_records_pva.db")


class ExampleEnum(StrictEnum):
    A = "Aaa"
    B = "Bbb"
    C = "Ccc"


class ExampleTable(Table):
    bool: Array1D[np.bool_]
    int: Array1D[np.int32]
    float: Array1D[np.float64]
    str: Sequence[str]
    enum: Sequence[ExampleEnum]


class ExampleCaDevice(EpicsDevice):
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


class ExamplePvaDevice(ExampleCaDevice):  # pva can support all signal types that ca can
    int8a: A[SignalRW[Array1D[np.int8]], PvSuffix("int8a")]
    uint16a: A[SignalRW[Array1D[np.uint16]], PvSuffix("uint16a")]
    uint32a: A[SignalRW[Array1D[np.uint32]], PvSuffix("uint32a")]
    int64a: A[SignalRW[Array1D[np.int64]], PvSuffix("int64a")]
    uint64a: A[SignalRW[Array1D[np.uint64]], PvSuffix("uint64a")]
    table: A[SignalRW[ExampleTable], PvSuffix("table")]
    ntndarray_data: A[SignalRW[Array1D[np.int64]], PvSuffix("ntndarray:data")]


async def connect_example_device(
    ioc: TestingIOC, protocol: Literal["ca", "pva"]
) -> ExamplePvaDevice | ExampleCaDevice:
    """Helper function to return a connected example device.

    Parameters
    ----------

    ioc: TestingIOC
        TestingIOC configured to provide the records needed for the device

    protocol: Literal["ca", "pva"]
        The transport protocol of the device

    Returns
    -------
    ExamplePvaDevice | ExampleCaDevice
        a connected EpicsDevice with signals of many EPICS record types
    """
    device_cls = ExamplePvaDevice if protocol == "pva" else ExampleCaDevice
    device = device_cls(f"{protocol}://{ioc.prefix_for(device_cls)}")
    await device.connect()
    return device


def get_example_ioc() -> TestingIOC:
    """Get TestingIOC instance with the example databases loaded.

    Returns
    -------
    TestingIOC
        instance with test_records.db loaded for ExampleCaDevice and
        test_records.db and test_records_pva.db loaded for ExamplePvaDevice.
    """
    ioc = TestingIOC()
    ioc.database_for(PVA_RECORDS, ExamplePvaDevice)
    ioc.database_for(CA_PVA_RECORDS, ExamplePvaDevice)
    ioc.database_for(CA_PVA_RECORDS, ExampleCaDevice)
    return ioc
