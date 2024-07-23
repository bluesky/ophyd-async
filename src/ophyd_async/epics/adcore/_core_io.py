from enum import Enum

from ophyd_async.core import Device
from ophyd_async.epics.signal import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_rw_rbv,
)

from ._utils import FileWriteMode, ImageMode


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


class NDArrayBaseIO(Device):
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


class NDPluginBaseIO(NDArrayBaseIO):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.nd_array_port = epics_signal_rw_rbv(str, prefix + "NDArrayPort")
        self.enable_callback = epics_signal_rw_rbv(Callback, prefix + "EnableCallbacks")
        self.nd_array_address = epics_signal_rw_rbv(int, prefix + "NDArrayAddress")
        self.array_size0 = epics_signal_r(int, prefix + "ArraySize0_RBV")
        self.array_size1 = epics_signal_r(int, prefix + "ArraySize1_RBV")
        super().__init__(prefix, name)


class NDPluginStatsIO(NDPluginBaseIO):
    pass


class DetectorState(str, Enum):
    """
    Default set of states of an AreaDetector driver.
    See definition in ADApp/ADSrc/ADDriver.h in https://github.com/areaDetector/ADCore
    """

    Idle = "Idle"
    Acquire = "Acquire"
    Readout = "Readout"
    Correct = "Correct"
    Saving = "Saving"
    Aborting = "Aborting"
    Error = "Error"
    Waiting = "Waiting"
    Initializing = "Initializing"
    Disconnected = "Disconnected"
    Aborted = "Aborted"


class ADBaseIO(NDArrayBaseIO):
    def __init__(self, prefix: str, name: str = "") -> None:
        # Define some signals
        self.acquire_time = epics_signal_rw_rbv(float, prefix + "AcquireTime")
        self.acquire_period = epics_signal_rw_rbv(float, prefix + "AcquirePeriod")
        self.num_images = epics_signal_rw_rbv(int, prefix + "NumImages")
        self.image_mode = epics_signal_rw_rbv(ImageMode, prefix + "ImageMode")
        self.detector_state = epics_signal_r(
            DetectorState, prefix + "DetectorState_RBV"
        )
        super().__init__(prefix, name=name)


class Compression(str, Enum):
    none = "None"
    nbit = "N-bit"
    szip = "szip"
    zlib = "zlib"
    blosc = "Blosc"
    bslz4 = "BSLZ4"
    lz4 = "LZ4"
    jpeg = "JPEG"


class NDFileHDFIO(NDPluginBaseIO):
    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        self.position_mode = epics_signal_rw_rbv(bool, prefix + "PositionMode")
        self.compression = epics_signal_rw_rbv(Compression, prefix + "Compression")
        self.num_extra_dims = epics_signal_rw_rbv(int, prefix + "NumExtraDims")
        self.file_path = epics_signal_rw_rbv(str, prefix + "FilePath")
        self.file_name = epics_signal_rw_rbv(str, prefix + "FileName")
        self.file_path_exists = epics_signal_r(bool, prefix + "FilePathExists_RBV")
        self.file_template = epics_signal_rw_rbv(str, prefix + "FileTemplate")
        self.full_file_name = epics_signal_r(str, prefix + "FullFileName_RBV")
        self.file_write_mode = epics_signal_rw_rbv(
            FileWriteMode, prefix + "FileWriteMode"
        )
        self.num_capture = epics_signal_rw_rbv(int, prefix + "NumCapture")
        self.num_captured = epics_signal_r(int, prefix + "NumCaptured_RBV")
        self.swmr_mode = epics_signal_rw_rbv(bool, prefix + "SWMRMode")
        self.lazy_open = epics_signal_rw_rbv(bool, prefix + "LazyOpen")
        self.capture = epics_signal_rw_rbv(bool, prefix + "Capture")
        self.flush_now = epics_signal_rw(bool, prefix + "FlushNow")
        self.xml_file_name = epics_signal_rw_rbv(str, prefix + "XMLFileName")
        self.array_size0 = epics_signal_r(int, prefix + "ArraySize0")
        self.array_size1 = epics_signal_r(int, prefix + "ArraySize1")
        self.create_dir_depth = epics_signal_rw(int, prefix + "CreateDirectory")
        super().__init__(prefix, name)
