from enum import Enum

from ophyd_async.core import Device
from ophyd_async.epics.signal import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_rw_rbv,
)

from ._utils import ADBaseDataType, FileWriteMode, ImageMode


class Callback(str, Enum):
    Enable = "Enable"
    Disable = "Disable"


class NDArrayBaseIO(Device):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.unique_id = epics_signal_r(int, prefix + "UniqueId_RBV")
        self.nd_attributes_file = epics_signal_rw(str, prefix + "NDAttributesFile")
        self.acquire = epics_signal_rw_rbv(bool, prefix + "Acquire")
        self.array_size_x = epics_signal_r(int, prefix + "ArraySizeX_RBV")
        self.array_size_y = epics_signal_r(int, prefix + "ArraySizeY_RBV")
        self.data_type = epics_signal_r(ADBaseDataType, prefix + "DataType_RBV")
        self.array_counter = epics_signal_rw_rbv(int, prefix + "ArrayCounter")
        # There is no _RBV for this one
        self.wait_for_plugins = epics_signal_rw(bool, prefix + "WaitForPlugins")
        super().__init__(name=name)


class NDPluginBaseIO(NDArrayBaseIO):
    def __init__(self, prefix: str, name: str = "") -> None:
        self.nd_array_port = epics_signal_rw_rbv(str, prefix + "NDArrayPort")
        self.enable_callbacks = epics_signal_rw_rbv(
            Callback, prefix + "EnableCallbacks"
        )
        self.nd_array_address = epics_signal_rw_rbv(int, prefix + "NDArrayAddress")
        self.array_size0 = epics_signal_r(int, prefix + "ArraySize0_RBV")
        self.array_size1 = epics_signal_r(int, prefix + "ArraySize1_RBV")
        super().__init__(prefix, name)


class NDPluginStatsIO(NDPluginBaseIO):
    """
    Plugin for computing statistics from an image or region of interest within an image.
    """

    def __init__(self, prefix: str, name: str = "") -> None:
        # Basic statistics
        self.compute_statistics = epics_signal_rw(bool, prefix + "ComputeStatistics")
        self.bgd_width = epics_signal_rw(int, prefix + "BgdWidth")
        self.total_array = epics_signal_rw(float, prefix + "TotalArray")
        # Centroid statistics
        self.compute_centroid = epics_signal_rw(bool, prefix + "ComputeCentroid")
        self.centroid_threshold = epics_signal_rw(float, prefix + "CentroidThreshold")
        # X and Y Profiles
        self.compute_profiles = epics_signal_rw(bool, prefix + "ComputeProfiles")
        self.profile_size_x = epics_signal_rw(int, prefix + "ProfileSizeX")
        self.profile_size_y = epics_signal_rw(int, prefix + "ProfileSizeY")
        self.cursor_x = epics_signal_rw(int, prefix + "CursorX")
        self.cursor_y = epics_signal_rw(int, prefix + "CursorY")
        # Array Histogram
        self.compute_histogram = epics_signal_rw(bool, prefix + "ComputeHistogram")
        self.hist_size = epics_signal_rw(int, prefix + "HistSize")
        self.hist_min = epics_signal_rw(float, prefix + "HistMin")
        self.hist_max = epics_signal_rw(float, prefix + "HistMax")
        super().__init__(prefix, name)


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
        self.create_directory = epics_signal_rw(int, prefix + "CreateDirectory")
        self.num_frames_chunks = epics_signal_r(int, prefix + "NumFramesChunks_RBV")
        self.chunk_size_auto = epics_signal_rw_rbv(bool, prefix + "ChunkSizeAuto")
        super().__init__(prefix, name)
