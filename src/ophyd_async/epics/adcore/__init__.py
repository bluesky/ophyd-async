"""Core components of the areaDetector software.

https://github.com/areaDetector/ADCore
"""

from ._acquire_logic import ADAcquireLogic, ADContAcqAcquireLogic
from ._data_logic import (
    ADHDFDataLogic,
    ADMultipartDataLogic,
    ADWriterType,
    NDArrayDescription,
    PluginSignalDataLogic,
)
from ._detector import AreaDetector, ContAcqDetector
from ._io import (
    NDROIIO,
    ADBaseColorMode,
    ADBaseDataType,
    ADBaseIO,
    ADCompression,
    ADFileWriteMode,
    ADImageMode,
    ADState,
    NDArrayBaseIO,
    NDCBFlushOnSoftTrgMode,
    NDCircularBuffIO,
    NDFileHDF5IO,
    NDFileIO,
    NDPluginBaseIO,
    NDPluginFileIO,
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
    prepare_exposures,
    trigger_info_from_num_images,
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
    "ADCompression",
    "NDFileHDF5IO",
    # TriggerLogic
    "prepare_exposures",
    "ADContAcqTriggerLogic",
    "trigger_info_from_num_images",
    # AcquireLogic
    "ADAcquireLogic",
    "ADContAcqAcquireLogic",
    # DataLogic
    "NDArrayDescription",
    "PluginSignalDataLogic",
    "ADHDFDataLogic",
    "ADMultipartDataLogic",
    "ADWriterType",
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
