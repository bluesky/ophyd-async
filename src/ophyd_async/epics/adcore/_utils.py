from dataclasses import dataclass
from enum import Enum

from ophyd_async.core import DEFAULT_TIMEOUT, SignalRW, T, wait_for_value
from ophyd_async.core._signal import SignalR


class ADBaseDataType(str, Enum):
    Int8 = "Int8"
    UInt8 = "UInt8"
    Int16 = "Int16"
    UInt16 = "UInt16"
    Int32 = "Int32"
    UInt32 = "UInt32"
    Int64 = "Int64"
    UInt64 = "UInt64"
    Float32 = "Float32"
    Float64 = "Float64"


def convert_ad_dtype_to_np(ad_dtype: ADBaseDataType) -> str:
    ad_dtype_to_np_dtype = {
        ADBaseDataType.Int8: "|i1",
        ADBaseDataType.UInt8: "|u1",
        ADBaseDataType.Int16: "<i2",
        ADBaseDataType.UInt16: "<u2",
        ADBaseDataType.Int32: "<i4",
        ADBaseDataType.UInt32: "<u4",
        ADBaseDataType.Int64: "<i8",
        ADBaseDataType.UInt64: "<u8",
        ADBaseDataType.Float32: "<f4",
        ADBaseDataType.Float64: "<f8",
    }
    return ad_dtype_to_np_dtype[ad_dtype]


def convert_pv_dtype_to_np(datatype: str) -> str:
    _pvattribute_to_ad_datatype = {
        "DBR_SHORT": ADBaseDataType.Int16,
        "DBR_ENUM": ADBaseDataType.Int16,
        "DBR_INT": ADBaseDataType.Int32,
        "DBR_LONG": ADBaseDataType.Int32,
        "DBR_FLOAT": ADBaseDataType.Float32,
        "DBR_DOUBLE": ADBaseDataType.Float64,
    }
    if datatype in ["DBR_STRING", "DBR_CHAR"]:
        np_datatype = "s40"
    elif datatype == "DBR_NATIVE":
        raise ValueError("Don't support DBR_NATIVE yet")
    else:
        try:
            np_datatype = convert_ad_dtype_to_np(_pvattribute_to_ad_datatype[datatype])
        except KeyError as e:
            raise ValueError(f"Invalid dbr type {datatype}") from e
    return np_datatype


def convert_param_dtype_to_np(datatype: str) -> str:
    _paramattribute_to_ad_datatype = {
        "INT": ADBaseDataType.Int32,
        "INT64": ADBaseDataType.Int64,
        "DOUBLE": ADBaseDataType.Float64,
    }
    if datatype in ["STRING"]:
        np_datatype = "s40"
    else:
        try:
            np_datatype = convert_ad_dtype_to_np(
                _paramattribute_to_ad_datatype[datatype]
            )
        except KeyError as e:
            raise ValueError(f"Invalid datatype {datatype}") from e
    return np_datatype


class FileWriteMode(str, Enum):
    single = "Single"
    capture = "Capture"
    stream = "Stream"


class ImageMode(str, Enum):
    single = "Single"
    multiple = "Multiple"
    continuous = "Continuous"


class NDAttributeDataType(str, Enum):
    INT = "INT"
    DOUBLE = "DOUBLE"
    STRING = "STRING"


class NDAttributePvDbrType(str, Enum):
    DBR_SHORT = "DBR_SHORT"
    DBR_ENUM = "DBR_ENUM"
    DBR_INT = "DBR_INT"
    DBR_LONG = "DBR_LONG"
    DBR_FLOAT = "DBR_FLOAT"
    DBR_DOUBLE = "DBR_DOUBLE"
    DBR_STRING = "DBR_STRING"
    DBR_CHAR = "DBR_CHAR"


@dataclass
class NDAttributePv:
    name: str  # name of attribute stamped on array, also scientifically useful name
    # when appended to device.name
    signal: SignalR  # caget the pv given by signal.source and attach to each frame
    dbrtype: NDAttributePvDbrType
    description: str = ""  # A description that appears in the HDF file as an attribute


@dataclass
class NDAttributeParam:
    name: str  # name of attribute stamped on array, also scientifically useful name
    # when appended to device.name
    param: str  # The parameter string as seen in the INP link of the record
    datatype: NDAttributeDataType  # The datatype of the parameter
    addr: int = 0  # The address as seen in the INP link of the record
    description: str = ""  # A description that appears in the HDF file as an attribute


async def stop_busy_record(
    signal: SignalRW[T],
    value: T,
    timeout: float = DEFAULT_TIMEOUT,
    status_timeout: float | None = None,
) -> None:
    await signal.set(value, wait=False, timeout=status_timeout)
    await wait_for_value(signal, value, timeout=timeout)
