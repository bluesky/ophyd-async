from enum import Enum

from ophyd_async.core import Device
from ophyd_async.epics.signal import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_rw_rbv,
)


class Callback(str, Enum):
    Enable = "Enable"
    Disable = "Disable"


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


class NDArrayBase(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.unique_id = epics_signal_r(int, prefix + "UniqueId_RBV")
        self.nd_attributes_file = epics_signal_rw(str, prefix + "NDAttributesFile")
        self.acquire = epics_signal_rw_rbv(bool, prefix + "Acquire")
        self.array_size_x = epics_signal_r(int, prefix + "ArraySizeX_RBV")
        self.array_size_y = epics_signal_r(int, prefix + "ArraySizeY_RBV")
        self.data_type = epics_signal_r(ADBaseDataType, prefix + "NDDataType_RBV")
        self.array_counter = epics_signal_rw_rbv(int, prefix + "ArrayCounter")
        # There is no _RBV for this one
        self.wait_for_plugins = epics_signal_rw(bool, prefix + "WaitForPlugins")

        super().__init__(name=name)


class NDPluginBase(NDArrayBase):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.nd_array_port = epics_signal_rw_rbv(str, prefix + "NDArrayPort")
        self.enable_callback = epics_signal_rw_rbv(Callback, prefix + "EnableCallbacks")
        self.nd_array_address = epics_signal_rw_rbv(int, prefix + "NDArrayAddress")
        self.array_size0 = epics_signal_r(int, prefix + "ArraySize0_RBV")
        self.array_size1 = epics_signal_r(int, prefix + "ArraySize1_RBV")
        super().__init__(prefix, name)


class NDPluginStatsIO(NDPluginBase):
    pass
