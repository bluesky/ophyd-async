"""Core components of the areaDetector software.

https://github.com/areaDetector/ADCore
"""

from ._arm_logic import ADArmLogic, ADContAcqArmLogic
from ._data_logic import ADHDFDataLogic, ADMultipartDataLogic, ADWriterType
from ._detector import AreaDetector
from ._io import (
    ADBaseDataType,
    ADBaseIO,
    ADCompression,
    ADFileWriteMode,
    ADImageMode,
    ADState,
    NDArrayBaseIO,
    NDCBFlushOnSoftTrgMode,
    NDFileHDFIO,
    NDFileIO,
    NDFilePluginIO,
    NDPluginBaseIO,
    NDPluginCBIO,
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
    "NDArrayBaseIO",
    "ADImageMode",
    "ADState",
    "ADBaseIO",
    "NDPluginBaseIO",
    "NDStatsIO",
    "NDROIStatNIO",
    "NDROIStatIO",
    "NDCBFlushOnSoftTrgMode",
    "NDPluginCBIO",
    "ADFileWriteMode",
    "NDFileIO",
    "NDFilePluginIO",
    "ADCompression",
    "NDFileHDFIO",
    # TriggerLogic
    "prepare_exposures",
    "ADContAcqTriggerLogic",
    # ArmLogic
    "ADArmLogic",
    "ADContAcqArmLogic",
    # DataLogic
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
