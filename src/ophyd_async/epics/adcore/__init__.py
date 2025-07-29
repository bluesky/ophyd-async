"""Core components of the areaDetector software.

https://github.com/areaDetector/ADCore
"""

from ._core_detector import AreaDetector, ContAcqAreaDetector
from ._core_io import (
    ADBaseDatasetDescriber,
    ADBaseIO,
    ADCompression,
    ADState,
    NDArrayBaseIO,
    NDCBFlushOnSoftTrgMode,
    NDFileHDFIO,
    NDFileIO,
    NDFilePluginIO,
    NDPluginBaseIO,
    NDPluginCBIO,
    NDPluginStatsIO,
    NDROIStatIO,
)
from ._core_logic import DEFAULT_GOOD_STATES, ADBaseContAcqController, ADBaseController
from ._core_writer import ADWriter
from ._hdf_writer import ADHDFWriter
from ._jpeg_writer import ADJPEGWriter
from ._single_trigger import SingleTriggerDetector
from ._tiff_writer import ADTIFFWriter
from ._utils import (
    ADBaseDataType,
    ADFileWriteMode,
    ADImageMode,
    NDAttributeDataType,
    NDAttributeParam,
    NDAttributePv,
    NDAttributePvDbrType,
    ndattributes_to_xml,
)

__all__ = [
    "ADBaseIO",
    "ADCompression",
    "ADBaseContAcqController",
    "AreaDetector",
    "ADState",
    "ContAcqAreaDetector",
    "NDArrayBaseIO",
    "NDFileIO",
    "NDFilePluginIO",
    "NDFileHDFIO",
    "NDPluginBaseIO",
    "NDPluginStatsIO",
    "NDROIStatIO",
    "DEFAULT_GOOD_STATES",
    "ADBaseDatasetDescriber",
    "ADBaseController",
    "ADWriter",
    "ADHDFWriter",
    "ADTIFFWriter",
    "ADJPEGWriter",
    "SingleTriggerDetector",
    "ADBaseDataType",
    "ADFileWriteMode",
    "ADImageMode",
    "NDAttributePv",
    "NDAttributeParam",
    "NDAttributeDataType",
    "NDAttributePvDbrType",
    "NDCBFlushOnSoftTrgMode",
    "NDPluginCBIO",
    "ndattributes_to_xml",
]
