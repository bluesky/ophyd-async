import asyncio
from typing import Annotated as A

from ophyd_async.core import DatasetDescriber, SignalR, SignalRW, StrictEnum
from ophyd_async.epics.core import EpicsDevice, PvSuffix

from ._utils import ADBaseDataType, ADFileWriteMode, ADImageMode, convert_ad_dtype_to_np


class ADCallbacks(StrictEnum):
    ENABLE = "Enable"
    DISABLE = "Disable"


class NDArrayBaseIO(EpicsDevice):
    """Class responsible for passing detector data from drivers to pluglins.

    This mirrors the interface provided by ADCore/db/NDArrayBase.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDArray.html
    """

    unique_id: A[SignalR[int], PvSuffix("UniqueId_RBV")]
    nd_attributes_file: A[SignalRW[str], PvSuffix("NDAttributesFile")]
    acquire: A[SignalRW[bool], PvSuffix.rbv("Acquire")]
    array_size_x: A[SignalR[int], PvSuffix("ArraySizeX_RBV")]
    array_size_y: A[SignalR[int], PvSuffix("ArraySizeY_RBV")]
    data_type: A[SignalR[ADBaseDataType], PvSuffix("DataType_RBV")]
    array_counter: A[SignalRW[int], PvSuffix.rbv("ArrayCounter")]
    # There is no _RBV for this one
    wait_for_plugins: A[SignalRW[bool], PvSuffix("WaitForPlugins")]


class ADBaseDatasetDescriber(DatasetDescriber):
    def __init__(self, driver: NDArrayBaseIO) -> None:
        self._driver = driver

    async def np_datatype(self) -> str:
        return convert_ad_dtype_to_np(await self._driver.data_type.get_value())

    async def shape(self) -> tuple[int, int]:
        shape = await asyncio.gather(
            self._driver.array_size_y.get_value(),
            self._driver.array_size_x.get_value(),
        )
        return shape


class NDPluginBaseIO(NDArrayBaseIO):
    """Base class from which plugins are derived.

    This mirrors the interface provided by ADCore/db/NDPluginBase.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDPluginDriver.html
    """

    nd_array_port: A[SignalRW[str], PvSuffix.rbv("NDArrayPort")]
    enable_callbacks: A[SignalRW[ADCallbacks], PvSuffix.rbv("EnableCallbacks")]
    nd_array_address: A[SignalRW[int], PvSuffix.rbv("NDArrayAddress")]
    array_size0: A[SignalR[int], PvSuffix("ArraySize0_RBV")]
    array_size1: A[SignalR[int], PvSuffix("ArraySize1_RBV")]
    queue_size: A[SignalRW[int], PvSuffix.rbv("QueueSize")]


class NDPluginStatsIO(NDPluginBaseIO):
    """Plugin for computing statistics from an image or ROI within an image.

    This mirrors the interface provided by ADCore/db/NDStats.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDPluginStats.html
    """

    # Basic statistics
    compute_statistics: A[SignalRW[bool], PvSuffix.rbv("ComputeStatistics")]
    bgd_width: A[SignalRW[int], PvSuffix.rbv("BgdWidth")]
    total: A[SignalR[float], PvSuffix.rbv("Total")]
    # Centroid statistics
    compute_centroid: A[SignalRW[bool], PvSuffix.rbv("ComputeCentroid")]
    centroid_threshold: A[SignalRW[float], PvSuffix.rbv("CentroidThreshold")]
    # X and Y Profiles
    compute_profiles: A[SignalRW[bool], PvSuffix.rbv("ComputeProfiles")]
    profile_size_x: A[SignalR[int], PvSuffix.rbv("ProfileSizeX")]
    profile_size_y: A[SignalR[int], PvSuffix.rbv("ProfileSizeY")]
    cursor_x: A[SignalRW[int], PvSuffix.rbv("CursorX")]
    cursor_y: A[SignalRW[int], PvSuffix.rbv("CursorY")]
    # Array Histogram
    compute_histogram: A[SignalRW[bool], PvSuffix.rbv("ComputeHistogram")]
    hist_size: A[SignalRW[int], PvSuffix.rbv("HistSize")]
    hist_min: A[SignalRW[float], PvSuffix.rbv("HistMin")]
    hist_max: A[SignalRW[float], PvSuffix.rbv("HistMax")]


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


class ADBaseIO(NDArrayBaseIO):
    """Base class from which areaDetector drivers are derived.

    This mirrors the interface provided by ADCore/db/ADBase.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/ADDriver.html
    """

    acquire_time: A[SignalRW[float], PvSuffix.rbv("AcquireTime")]
    acquire_period: A[SignalRW[float], PvSuffix.rbv("AcquirePeriod")]
    num_images: A[SignalRW[int], PvSuffix.rbv("NumImages")]
    image_mode: A[SignalRW[ADImageMode], PvSuffix.rbv("ImageMode")]
    detector_state: A[SignalR[ADState], PvSuffix("DetectorState_RBV")]


class ADCompression(StrictEnum):
    NONE = "None"
    NBIT = "N-bit"
    SZIP = "szip"
    ZLIB = "zlib"
    BLOSC = "Blosc"
    BSLZ4 = "BSLZ4"
    LZ4 = "LZ4"
    JPEG = "JPEG"


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
    capture: A[SignalRW[bool], PvSuffix.rbv("Capture")]
    array_size0: A[SignalR[int], PvSuffix("ArraySize0")]
    array_size1: A[SignalR[int], PvSuffix("ArraySize1")]
    create_directory: A[SignalRW[int], PvSuffix("CreateDirectory")]


class NDFilePluginIO(NDPluginBaseIO, NDFileIO):
    """Base class from which file plugins are derived.

    This mirrors the interface provided by ADCore/db/NDFilePlugin.template.
    See HTML docs at https://areadetector.github.io/areaDetector/ADCore/NDPluginFile.html
    """

    ...


class NDFileHDFIO(NDFilePluginIO):
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
    num_frames_chunks: A[SignalR[int], PvSuffix("NumFramesChunks_RBV")]
    chunk_size_auto: A[SignalRW[bool], PvSuffix.rbv("ChunkSizeAuto")]
    lazy_open: A[SignalRW[bool], PvSuffix.rbv("LazyOpen")]


class NDCBFlushOnSoftTrgMode(StrictEnum):
    ON_NEW_IMAGE = "OnNewImage"
    IMMEDIATELY = "Immediately"


class NDPluginCBIO(NDPluginBaseIO):
    pre_count: A[SignalRW[int], PvSuffix.rbv("PreCount")]
    post_count: A[SignalRW[int], PvSuffix.rbv("PostCount")]
    preset_trigger_count: A[SignalRW[int], PvSuffix.rbv("PresetTriggerCount")]
    trigger: A[SignalRW[bool], PvSuffix.rbv("Trigger")]
    capture: A[SignalRW[bool], PvSuffix.rbv("Capture")]
    flush_on_soft_trg: A[
        SignalRW[NDCBFlushOnSoftTrgMode], PvSuffix.rbv("FlushOnSoftTrg")
    ]
