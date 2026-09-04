"""Core components of the areaDetector software.

https://github.com/areaDetector/ADCore
"""

from ._acquire_logic import ADAcquireLogic, ADContAcqAcquireLogic
from ._data_logic import (
    ADHDFDataLogic,
    ADMultipartDataLogic,
    ADWriterFactory,
    NDArrayDescription,
    PluginSignalDataLogic,
)
from ._detector import AreaDetector, ContAcqDetector
from ._io import (
    NDROIIO,
    ADBaseColorMode,
    ADBaseDataType,
    ADBaseIO,
    ADBloscCompressor,
    ADBloscShuffle,
    ADCompressMode,
    ADCompressor,
    ADFileWriteMode,
    ADImageMode,
    ADState,
    NDArrayBaseIO,
    NDCBFlushOnSoftTrgMode,
    NDCircularBuffIO,
    NDCodecIO,
    NDCodecStatus,
    NDFileHDF5Compression,
    NDFileHDF5IO,
    NDFileIO,
    NDPluginBaseIO,
    NDPluginFileIO,
    NDProcessFilterCallbacks,
    NDProcessFilterType,
    NDProcessIO,
    NDROIStatIO,
    NDROIStatNIO,
    NDStatsIO,
)
from ._ndattribute import (
    NDAttributeDataType,
    NDAttributeParam,
    NDAttributePv,
    NDAttributePvDbrType,
    ndattributes_to_xml,
)
from ._plan_stubs import setup_ndattributes, setup_ndstats_sum
from ._trigger_logic import (
    ADContAcqTriggerLogic,
    default_trigger_info_from_detector_settings,
    prepare_exposures,
    prepare_exposures_per_collection,
)

__all__ = [
    # ADCore IOs
    "ADBaseDataType",
    "ADBaseColorMode",
    "NDArrayBaseIO",
    "ADImageMode",
    "ADState",
    "ADBaseIO",
    "NDPluginBaseIO",
    "NDROIIO",
    "NDStatsIO",
    "NDROIStatNIO",
    "NDROIStatIO",
    "NDCBFlushOnSoftTrgMode",
    "NDCircularBuffIO",
    "ADFileWriteMode",
    "NDFileIO",
    "NDPluginFileIO",
    "NDFileHDF5Compression",
    "NDFileHDF5IO",
    "NDCodecIO",
    "NDCodecStatus",
    "NDProcessIO",
    "NDProcessFilterType",
    "NDProcessFilterCallbacks",
    "ADCompressor",
    "ADCompressMode",
    "ADBloscCompressor",
    "ADBloscShuffle",
    # TriggerLogic
    "prepare_exposures",
    "prepare_exposures_per_collection",
    "ADContAcqTriggerLogic",
    "default_trigger_info_from_detector_settings",
    # AcquireLogic
    "ADAcquireLogic",
    "ADContAcqAcquireLogic",
    # DataLogic
    "NDArrayDescription",
    "PluginSignalDataLogic",
    "ADHDFDataLogic",
    "ADMultipartDataLogic",
    "ADWriterFactory",
    # Detector
    "AreaDetector",
    "ContAcqDetector",
    # NDAttributes
    "NDAttributeDataType",
    "NDAttributePvDbrType",
    "NDAttributePv",
    "NDAttributeParam",
    "ndattributes_to_xml",
    "setup_ndattributes",
    "setup_ndstats_sum",
]
