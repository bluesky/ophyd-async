from collections.abc import Sequence
from pathlib import Path
from typing import Annotated as A

import numpy as np

from ophyd_async.core import Array1D, SignalR, SignalRW, StrictEnum, Table
from ophyd_async.core._utils import SubsetEnum
from ophyd_async.epics.core import EpicsDevice, PvSuffix

from ._utils import TestingIOC, generate_random_pv_prefix

CA_PVA_RECORDS = Path(__file__).parent / "test_records.db"
PVA_RECORDS = Path(__file__).parent / "test_records_pva.db"


class ExampleEnum(StrictEnum):
    A = "Aaa"
    B = "Bbb"
    C = "Ccc"


class ExampleSubsetEnum(SubsetEnum):
    A = "Aaa"
    B = "Bbb"


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
    longstr: A[SignalRW[str], PvSuffix("longstr")]
    longstr2: A[SignalRW[str], PvSuffix("longstr2.VAL$")]
    my_bool: A[SignalRW[bool], PvSuffix("bool")]
    enum: A[SignalRW[ExampleEnum], PvSuffix("enum")]
    enum2: A[SignalRW[ExampleEnum], PvSuffix("enum2")]
    subset_enum: A[SignalRW[ExampleSubsetEnum], PvSuffix("subset_enum")]
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
    ntndarray: A[SignalR[np.ndarray], PvSuffix("ntndarray")]


class ExampleIocAndDevices:
    def __init__(self):
        self.prefix = generate_random_pv_prefix()
        self.ioc = TestingIOC()
        # Create supporting records and ExampleCaDevice
        ca_prefix = f"{self.prefix}ca:"
        self.ioc.add_database(CA_PVA_RECORDS, device=ca_prefix)
        self.ca_device = ExampleCaDevice(f"ca://{ca_prefix}")
        # Create supporting records and ExamplePvaDevice
        pva_prefix = f"{self.prefix}pva:"
        self.ioc.add_database(CA_PVA_RECORDS, device=pva_prefix)
        self.ioc.add_database(PVA_RECORDS, device=pva_prefix)
        self.pva_device = ExamplePvaDevice(f"pva://{pva_prefix}")

    def get_signal(self, protocol: str, name: str) -> SignalRW:
        device = getattr(self, f"{protocol}_device")
        return getattr(device, name)

    def get_pv(self, protocol: str, name: str) -> str:
        return f"{protocol}://{self.prefix}{protocol}:{name}"
