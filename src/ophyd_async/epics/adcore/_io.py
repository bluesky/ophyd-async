from typing import Annotated as A
from typing import TypeVar

import numpy as np

from ophyd_async.core import (
    Array1D,
    DeviceVector,
    EnableDisable,
    SignalR,
    SignalRW,
    StandardReadable,
    StrictEnum,
    SubsetEnum,
    SupersetEnum,
    non_zero,
)
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import EpicsDevice, EpicsOptions, PvSuffix

# Common classes for drivers and plugins


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


class ADBaseColorMode(SupersetEnum):
    MONO = "Mono"
    BAYER = "Bayer"
    RGB1 = "RGB1"
    RGB2 = "RGB2"
    RGB3 = "RGB3"
    YUV444 = "YUV444"
    YUV422 = "YUV422"
    YUV421 = "YUV421"


class NDArrayBaseIO(EpicsDevice):
    """Class responsible for passing detector data from drivers to plugins.

    This mirrors the interface provided by ADCore/db/NDArrayBase.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDArray.html
    """

    port_name: A[SignalR[str], PvSuffix("PortName_RBV")]
    unique_id: A[SignalR[int], PvSuffix("UniqueId_RBV")]
    nd_attributes_file: A[SignalRW[str], PvSuffix("NDAttributesFile")]

    # The array_size_x/y/z signals are used when outputting an NDArray
    # (i.e. from a driver)
    array_size_x: A[SignalR[int], PvSuffix("ArraySizeX_RBV")]
    array_size_y: A[SignalR[int], PvSuffix("ArraySizeY_RBV")]
    array_size_z: A[SignalR[int], PvSuffix("ArraySizeZ_RBV")]

    # The array_size0/1/2 signals are used when receiving an NDArray
    # (i.e. in a plugin)
    array_size0: A[SignalR[int], PvSuffix("ArraySize0_RBV")]
    array_size1: A[SignalR[int], PvSuffix("ArraySize1_RBV")]
    array_size2: A[SignalR[int], PvSuffix("ArraySize2_RBV")]

    color_mode: A[SignalR[ADBaseColorMode], PvSuffix("ColorMode_RBV")]
    data_type: A[SignalR[ADBaseDataType], PvSuffix("DataType_RBV")]
    array_counter: A[SignalRW[int], PvSuffix.rbv("ArrayCounter")]

    # Version information may be useful to include in metadata
    ad_core_version: A[SignalR[str], PvSuffix("ADCoreVersion_RBV")]
    driver_version: A[SignalR[str], PvSuffix("DriverVersion_RBV")]


# Classes for drivers


class ADImageMode(SubsetEnum):
    SINGLE = "Single"
    MULTIPLE = "Multiple"
    CONTINUOUS = "Continuous"


class ADState(StrictEnum):
    """Default set of states of an AreaDetector driver.

    See definition in ADApp/ADSrc/ADDriver.h in https://github.com/areaDetector/ADCore.
    """

    IDLE = "Idle"
    ACQUIRE = "Acquire"
    READOUT = "Readout"
    CORRECT = "Correct"
    SAVING = "Saving"
    ABORTING = "Aborting"
    ERROR = "Error"
    WAITING = "Waiting"
    INITIALIZING = "Initializing"
    DISCONNECTED = "Disconnected"
    ABORTED = "Aborted"


#: TypeVar for any `ADBaseIO` subclass
ADBaseIOT = TypeVar("ADBaseIOT", bound="ADBaseIO")


class ADBaseIO(StandardReadable, NDArrayBaseIO):
    """Base class from which areaDetector drivers are derived.

    This mirrors the interface provided by ADCore/db/ADBase.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/ADDriver.html

    The interface deviates from the most up to date version of ADBase as it contains
    some signals that are now in NDArrayBaseIO. This is to maintain backwards
    compatibility with changes made in https://github.com/areaDetector/ADCore/blob/master/RELEASE.md#asynndarraydriver-addriver
    """

    acquire_time: A[SignalRW[float], PvSuffix.rbv("AcquireTime"), Format.CONFIG_SIGNAL]
    acquire_period: A[
        SignalRW[float], PvSuffix.rbv("AcquirePeriod"), Format.CONFIG_SIGNAL
    ]
    num_images: A[SignalRW[int], PvSuffix.rbv("NumImages"), Format.CONFIG_SIGNAL]
    image_mode: A[
        SignalRW[ADImageMode], PvSuffix.rbv("ImageMode"), Format.CONFIG_SIGNAL
    ]
    detector_state: A[SignalR[ADState], PvSuffix("DetectorState_RBV")]

    # The following signals have been moved from NDArrayBaseIO for backwards
    # compatibility
    acquire: A[SignalRW[bool], PvSuffix.rbv("Acquire"), EpicsOptions(wait=non_zero)]

    # There is no _RBV for this one
    wait_for_plugins: A[SignalRW[bool], PvSuffix("WaitForPlugins")]

    manufacturer: A[SignalR[str], PvSuffix("Manufacturer_RBV"), Format.CONFIG_SIGNAL]
    model: A[SignalR[str], PvSuffix("Model_RBV"), Format.CONFIG_SIGNAL]
    serial_number: A[SignalR[str], PvSuffix("SerialNumber_RBV"), Format.CONFIG_SIGNAL]
    sdk_version: A[SignalR[str], PvSuffix("SDKVersion_RBV"), Format.CONFIG_SIGNAL]
    firmware_version: A[
        SignalR[str], PvSuffix("FirmwareVersion_RBV"), Format.CONFIG_SIGNAL
    ]


# Classes for plugins
#: TypeVar for any `NDPluginBaseIO` subclass
NDPluginBaseIOT = TypeVar("NDPluginBaseIOT", bound="NDPluginBaseIO")


class NDPluginBaseIO(NDArrayBaseIO):
    """Base class from which plugins are derived.

    This mirrors the interface provided by ADCore/db/NDPluginBase.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDPluginDriver.html
    """

    nd_array_port: A[SignalRW[str], PvSuffix.rbv("NDArrayPort")]
    enable_callbacks: A[SignalRW[EnableDisable], PvSuffix.rbv("EnableCallbacks")]
    nd_array_address: A[SignalRW[int], PvSuffix.rbv("NDArrayAddress")]
    queue_size: A[SignalRW[int], PvSuffix.rbv("QueueSize")]


class NDROIIO(StandardReadable, NDPluginBaseIO):
    """Plugin for taking a region of an NDArray.

    This mirrors the interface provided by ADCore/db/NDROI.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDPluginROI.html
    """

    min_x: A[SignalRW[int], PvSuffix.rbv("MinX"), Format.CONFIG_SIGNAL]
    min_y: A[SignalRW[int], PvSuffix.rbv("MinY"), Format.CONFIG_SIGNAL]
    size_x: A[SignalRW[int], PvSuffix.rbv("SizeX"), Format.CONFIG_SIGNAL]
    size_y: A[SignalRW[int], PvSuffix.rbv("SizeY"), Format.CONFIG_SIGNAL]
    size_z: A[SignalRW[int], PvSuffix.rbv("SizeZ")]

    bin_x: A[SignalRW[int], PvSuffix.rbv("BinX")]
    bin_y: A[SignalRW[int], PvSuffix.rbv("BinY")]
    bin_z: A[SignalRW[int], PvSuffix.rbv("BinZ")]


class NDProcessIO(NDPluginBaseIO):
    """Plugin for performing processing on an NDArrray.

    This mirrors the interface provided by ADCore/db/NDProcess.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDPluginProcess.html
    """

    enable_offset_scale: A[SignalRW[EnableDisable], PvSuffix.rbv("EnableOffsetScale")]
    scale: A[SignalRW[float], PvSuffix.rbv("Scale")]


class NDStatsTSAcquireMode(StrictEnum):
    """Whether an NDPluginStats time series stops when full or wraps around.

    Mirrors the ``TSAcquireMode`` record in
    ADCore/db/NDPluginTimeSeries.template.
    """

    FIXED_LENGTH = "Fixed length"
    CIRCULAR_BUFFER = "Circular buffer"


class NDStatsIO(StandardReadable, NDPluginBaseIO):
    """Plugin for computing statistics from an image or ROI within an image.

    This mirrors the interface provided by ADCore/db/NDStats.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDPluginStats.html
    """

    # Basic statistics
    compute_statistics: A[
        SignalRW[bool], PvSuffix.rbv("ComputeStatistics"), Format.CONFIG_SIGNAL
    ]
    bgd_width: A[SignalRW[int], PvSuffix.rbv("BgdWidth"), Format.CONFIG_SIGNAL]
    min_value: A[
        SignalR[float], PvSuffix("MinValue_RBV"), Format.HINTED_UNCACHED_SIGNAL
    ]
    min_x: A[SignalR[float], PvSuffix("MinX_RBV"), Format.UNCACHED_SIGNAL]
    min_y: A[SignalR[float], PvSuffix("MinY_RBV"), Format.UNCACHED_SIGNAL]
    max_value: A[
        SignalR[float], PvSuffix("MaxValue_RBV"), Format.HINTED_UNCACHED_SIGNAL
    ]
    max_x: A[SignalR[float], PvSuffix("MaxX_RBV"), Format.UNCACHED_SIGNAL]
    max_y: A[SignalR[float], PvSuffix("MaxY_RBV"), Format.UNCACHED_SIGNAL]
    mean_value: A[
        SignalR[float], PvSuffix("MeanValue_RBV"), Format.HINTED_UNCACHED_SIGNAL
    ]
    sigma: A[SignalR[float], PvSuffix("Sigma_RBV")]
    total: A[SignalR[float], PvSuffix("Total_RBV"), Format.HINTED_UNCACHED_SIGNAL]
    net: A[SignalR[float], PvSuffix("Net_RBV")]
    # Time series. NDStats delegates its time series to an embedded
    # NDPluginTimeSeries instance under an inner "TS:" prefix, so each statistic
    # is also exposed as a fixed-length array. ts_num_points sizes the buffer,
    # ts_acquire erases and starts it (writing 1 clears the arrays and resets
    # ts_current_point to 0), ts_current_point reports progress, ts_total holds
    # the Total series and ts_timestamp holds the per-point acquisition times.
    # These are not registered as readables: the scalars above serve read(), and
    # the arrays are consumed by StatsTimeSeriesDataLogic as event pages.
    ts_acquire: A[SignalRW[bool], PvSuffix("TS:TSAcquire")]
    ts_num_points: A[SignalRW[int], PvSuffix.rbv("TS:TSNumPoints")]
    ts_current_point: A[SignalR[int], PvSuffix("TS:TSCurrentPoint")]
    ts_acquiring: A[SignalR[bool], PvSuffix("TS:TSAcquiring")]
    ts_acquire_mode: A[SignalRW[NDStatsTSAcquireMode], PvSuffix.rbv("TS:TSAcquireMode")]
    ts_total: A[SignalR[Array1D[np.float64]], PvSuffix("TS:TSTotal")]
    ts_timestamp: A[SignalR[Array1D[np.float64]], PvSuffix("TS:TSTimestamp")]
    # Centroid statistics
    compute_centroid: A[
        SignalRW[bool], PvSuffix.rbv("ComputeCentroid"), Format.CONFIG_SIGNAL
    ]
    centroid_threshold: A[
        SignalRW[float], PvSuffix.rbv("CentroidThreshold"), Format.CONFIG_SIGNAL
    ]
    centroid_x: A[SignalR[float], PvSuffix("CentroidX_RBV")]
    centroid_y: A[SignalR[float], PvSuffix("CentroidY_RBV")]
    sigma_x: A[SignalR[float], PvSuffix("SigmaX_RBV")]
    sigma_y: A[SignalR[float], PvSuffix("SigmaY_RBV")]
    sigma_xy: A[SignalR[float], PvSuffix("SigmaXY_RBV")]
    # X and Y Profiles
    compute_profiles: A[
        SignalRW[bool], PvSuffix.rbv("ComputeProfiles"), Format.CONFIG_SIGNAL
    ]
    profile_size_x: A[SignalR[int], PvSuffix("ProfileSizeX_RBV")]
    profile_size_y: A[SignalR[int], PvSuffix("ProfileSizeY_RBV")]
    cursor_x: A[SignalRW[int], PvSuffix.rbv("CursorX"), Format.CONFIG_SIGNAL]
    cursor_y: A[SignalRW[int], PvSuffix.rbv("CursorY"), Format.CONFIG_SIGNAL]
    # Array Histogram
    compute_histogram: A[
        SignalRW[bool], PvSuffix.rbv("ComputeHistogram"), Format.CONFIG_SIGNAL
    ]
    hist_size: A[SignalRW[int], PvSuffix.rbv("HistSize"), Format.CONFIG_SIGNAL]
    hist_min: A[SignalRW[float], PvSuffix.rbv("HistMin"), Format.CONFIG_SIGNAL]
    hist_max: A[SignalRW[float], PvSuffix.rbv("HistMax"), Format.CONFIG_SIGNAL]


class NDROIStatNIO(StandardReadable, EpicsDevice):
    """Defines the parameters for a single ROI used for statistics calculation.

    This mirrors the interface provided by ADCore/db/NDROIStatN.template.
    See definition in ADApp/pluginSrc/NDPluginROIStat.h in https://github.com/areaDetector/ADCore.
    """

    name_: A[SignalRW[str], PvSuffix("Name")]
    use: A[SignalRW[bool], PvSuffix.rbv("Use"), Format.CONFIG_SIGNAL]
    min_x: A[SignalRW[int], PvSuffix.rbv("MinX"), Format.CONFIG_SIGNAL]
    min_y: A[SignalRW[int], PvSuffix.rbv("MinY"), Format.CONFIG_SIGNAL]
    size_x: A[SignalRW[int], PvSuffix.rbv("SizeX"), Format.CONFIG_SIGNAL]
    size_y: A[SignalRW[int], PvSuffix.rbv("SizeY"), Format.CONFIG_SIGNAL]
    min_value: A[
        SignalR[float], PvSuffix("MinValue_RBV"), Format.HINTED_UNCACHED_SIGNAL
    ]
    max_value: A[
        SignalR[float], PvSuffix("MaxValue_RBV"), Format.HINTED_UNCACHED_SIGNAL
    ]
    mean_value: A[
        SignalR[float], PvSuffix("MeanValue_RBV"), Format.HINTED_UNCACHED_SIGNAL
    ]
    total: A[SignalR[float], PvSuffix("Total_RBV"), Format.HINTED_UNCACHED_SIGNAL]


class NDROIStatIO(NDPluginBaseIO):
    """Plugin for calculating basic statistics for multiple ROIs.

    Each ROI is implemented as an instance of NDROIStatNIO,
    and the collection of ROIs is held as a DeviceVector.

    This mirrors the interface provided by ADCore/db/NDROIStat.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDPluginROIStat.html
    """

    def __init__(self, prefix, num_channels=8, with_pvi=False, name=""):
        self.channels = DeviceVector(
            {i: NDROIStatNIO(f"{prefix}{i}:") for i in range(1, num_channels + 1)}
        )
        super().__init__(prefix, with_pvi, name)


class NDCBFlushOnSoftTrgMode(StrictEnum):
    ON_NEW_IMAGE = "OnNewImage"
    IMMEDIATELY = "Immediately"


class NDCircularBuffIO(NDPluginBaseIO):
    """Plugin for flow control of arrays based on NDAttributes.

    This mirrors the interface provided by ADCore/db/NDCircularBuff.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDPluginCircularBuff.html
    """

    pre_count: A[SignalRW[int], PvSuffix.rbv("PreCount")]
    post_count: A[SignalRW[int], PvSuffix.rbv("PostCount")]
    preset_trigger_count: A[SignalRW[int], PvSuffix.rbv("PresetTriggerCount")]
    trigger_: A[SignalRW[bool], PvSuffix.rbv("Trigger"), EpicsOptions(wait=non_zero)]
    capture: A[SignalRW[bool], PvSuffix.rbv("Capture"), EpicsOptions(wait=non_zero)]
    flush_on_soft_trg: A[
        SignalRW[NDCBFlushOnSoftTrgMode], PvSuffix.rbv("FlushOnSoftTrg")
    ]


# Classes for filewriters


class ADFileWriteMode(StrictEnum):
    SINGLE = "Single"
    CAPTURE = "Capture"
    STREAM = "Stream"


class NDFileIO(NDArrayBaseIO):
    """Base class from which file writing drivers are derived.

    This mirrors the interface provided by ADCore/ADApp/Db/NDFile.template.
    It does not include any plugin-related fields, for that see NDFilePluginIO.
    """

    file_path: A[SignalRW[str], PvSuffix.rbv("FilePath")]
    file_name: A[SignalRW[str], PvSuffix.rbv("FileName")]
    file_path_exists: A[SignalR[bool], PvSuffix("FilePathExists_RBV")]
    file_template: A[SignalRW[str], PvSuffix.rbv("FileTemplate")]
    full_file_name: A[SignalR[str], PvSuffix("FullFileName_RBV")]
    file_number: A[SignalRW[int], PvSuffix("FileNumber")]
    auto_increment: A[SignalRW[bool], PvSuffix("AutoIncrement")]
    file_write_mode: A[SignalRW[ADFileWriteMode], PvSuffix.rbv("FileWriteMode")]
    num_capture: A[SignalRW[int], PvSuffix.rbv("NumCapture")]
    num_captured: A[SignalR[int], PvSuffix("NumCaptured_RBV")]
    capture: A[SignalRW[bool], PvSuffix.rbv("Capture"), EpicsOptions(wait=non_zero)]
    array_size0: A[SignalR[int], PvSuffix("ArraySize0")]
    array_size1: A[SignalR[int], PvSuffix("ArraySize1")]
    create_directory: A[SignalRW[int], PvSuffix("CreateDirectory")]


NDPluginFileIOT = TypeVar("NDPluginFileIOT", bound="NDPluginFileIO")


class NDPluginFileIO(NDPluginBaseIO, NDFileIO):
    """Base class from which file plugins are derived.

    This mirrors the interface provided by ADCore/db/NDFile.template when added to
    NDPluginBase.template
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDPluginFile.html
    """

    ...


class ADCompression(StrictEnum):
    NONE = "None"
    NBIT = "N-bit"
    SZIP = "szip"
    ZLIB = "zlib"
    BLOSC = "Blosc"
    BSLZ4 = "BSLZ4"
    LZ4 = "LZ4"
    JPEG = "JPEG"


class NDFileHDF5IO(NDPluginFileIO):
    """Plugin for storing data in HDF5 file format.

    This mirrors the interface provided by ADCore/db/NDFileHDF5.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDFileHDF5.html
    """

    position_mode: A[SignalRW[bool], PvSuffix.rbv("PositionMode")]
    compression: A[SignalRW[ADCompression], PvSuffix.rbv("Compression")]
    num_extra_dims: A[SignalRW[int], PvSuffix.rbv("NumExtraDims")]
    swmr_mode: A[SignalRW[bool], PvSuffix.rbv("SWMRMode")]
    flush_now: A[SignalRW[bool], PvSuffix("FlushNow")]
    xml_file_name: A[SignalRW[str], PvSuffix.rbv("XMLFileName")]
    num_frames_chunks: A[SignalRW[int], PvSuffix.rbv("NumFramesChunks")]
    chunk_size_auto: A[SignalRW[bool], PvSuffix.rbv("ChunkSizeAuto")]
    lazy_open: A[SignalRW[bool], PvSuffix.rbv("LazyOpen")]
