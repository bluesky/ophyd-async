"""Core components of the areaDetector software.

https://github.com/areaDetector/ADCore
"""

from ._arm_logic import ADArmLogic, ADContAcqArmLogic
from ._data_logic import (
    ADHDFDataLogic,
    ADMultipartDataLogic,
    ADWriterType,
    NDArrayDescription,
    PluginSignalDataLogic,
)
from ._detector import AreaDetector
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
from ._trigger_logic import ADContAcqTriggerLogic, prepare_exposures

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
    # ArmLogic
    "ADArmLogic",
    "ADContAcqArmLogic",
    # DataLogic
    "NDArrayDescription",
    "PluginSignalDataLogic",
    "ADHDFDataLogic",
    "ADMultipartDataLogic",
    "ADWriterType",
    # AreaDetector
    "AreaDetector",
    # NDAttributes
    "NDAttributeDataType",
    "NDAttributePvDbrType",
    "NDAttributePv",
    "NDAttributeParam",
    "ndattributes_to_xml",
]
