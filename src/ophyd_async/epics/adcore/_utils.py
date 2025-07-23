from dataclasses import dataclass

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    SignalDatatypeT,
    SignalR,
    SignalRW,
    StrictEnum,
    SubsetEnum,
    SupersetEnum,
    wait_for_value,
)


class ADBaseDataType(SupersetEnum):
    INT8 = "Int8"
    UINT8 = "UInt8"
    INT16 = "Int16"
    UINT16 = "UInt16"
    INT32 = "Int32"
    UINT32 = "UInt32"
    INT64 = "Int64"
    UINT64 = "UInt64"
    FLOAT32 = "Float32"
    FLOAT64 = "Float64"
    # Driver database override will blank the enum string if it doesn't
    # support a datatype
    UNDEFINED = ""


def convert_ad_dtype_to_np(ad_dtype: ADBaseDataType) -> str:
    ad_dtype_to_np_dtype = {
        ADBaseDataType.INT8: "|i1",
        ADBaseDataType.UINT8: "|u1",
        ADBaseDataType.INT16: "<i2",
        ADBaseDataType.UINT16: "<u2",
        ADBaseDataType.INT32: "<i4",
        ADBaseDataType.UINT32: "<u4",
        ADBaseDataType.INT64: "<i8",
        ADBaseDataType.UINT64: "<u8",
        ADBaseDataType.FLOAT32: "<f4",
        ADBaseDataType.FLOAT64: "<f8",
    }
    np_type = ad_dtype_to_np_dtype.get(ad_dtype)
    if np_type is None:
        raise ValueError(
            "Areadetector driver has a blank DataType, this is not supported"
        )
    return np_type


def convert_pv_dtype_to_np(datatype: str) -> str:
    _pvattribute_to_ad_datatype = {
        "DBR_SHORT": ADBaseDataType.INT16,
        "DBR_ENUM": ADBaseDataType.INT16,
        "DBR_INT": ADBaseDataType.INT32,
        "DBR_LONG": ADBaseDataType.INT32,
        "DBR_FLOAT": ADBaseDataType.FLOAT32,
        "DBR_DOUBLE": ADBaseDataType.FLOAT64,
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
        "INT": ADBaseDataType.INT32,
        "INT64": ADBaseDataType.INT64,
        "DOUBLE": ADBaseDataType.FLOAT64,
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


class ADFileWriteMode(StrictEnum):
    SINGLE = "Single"
    CAPTURE = "Capture"
    STREAM = "Stream"


class ADImageMode(SubsetEnum):
    SINGLE = "Single"
    MULTIPLE = "Multiple"
    CONTINUOUS = "Continuous"


class NDAttributeDataType(StrictEnum):
    INT = "INT"
    DOUBLE = "DOUBLE"
    STRING = "STRING"


class NDAttributePvDbrType(StrictEnum):
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
    signal: SignalRW[SignalDatatypeT],
    value: SignalDatatypeT,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    await signal.set(value, wait=False)
    await wait_for_value(signal, value, timeout=timeout)
