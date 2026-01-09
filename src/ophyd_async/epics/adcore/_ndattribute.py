from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from xml.etree import ElementTree as ET

import numpy as np

from ophyd_async.core import SignalR


class NDAttributeDataType(Enum):
    INT = np.dtype(np.int32).str
    INT64 = np.dtype(np.int64).str
    DOUBLE = np.dtype(np.float64).str
    STRING = "S40"


class NDAttributePvDbrType(Enum):
    DBR_SHORT = np.dtype(np.int16).str
    DBR_ENUM = np.dtype(np.int16).str
    DBR_INT = np.dtype(np.int32).str
    DBR_LONG = np.dtype(np.int32).str
    DBR_FLOAT = np.dtype(np.float32).str
    DBR_DOUBLE = np.dtype(np.float64).str
    DBR_STRING = "S40"
    DBR_CHAR = np.dtype(np.int8).str


@dataclass
class NDAttributePv:
    name: str  # name of attribute stamped on array, also scientifically useful name
    # when appended to device.name
    signal: SignalR  # caget the pv given by signal.source and attach to each frame
    dbrtype: NDAttributePvDbrType
    description: str = ""  # A description that appears in the HDF file as an attribute


@dataclass
class NDAttributeParam:
    name: str  # name of attribute stamped on array, also scientifically useful name
    # when appended to device.name
    param: str  # The parameter string as seen in the INP link of the record
    datatype: NDAttributeDataType  # The datatype of the parameter
    addr: int = 0  # The address as seen in the INP link of the record
    description: str = ""  # A description that appears in the HDF file as an attribute


def ndattributes_to_xml(
    ndattributes: Sequence[NDAttributeParam | NDAttributePv],
) -> str:
    """Convert a set of NDAttribute params to XML."""
    root = ET.Element("Attributes")
    for ndattribute in ndattributes:
        if isinstance(ndattribute, NDAttributeParam):
            ET.SubElement(
                root,
                "Attribute",
                name=ndattribute.name,
                type="PARAM",
                source=ndattribute.param,
                addr=str(ndattribute.addr),
                datatype=ndattribute.datatype.value,
                description=ndattribute.description,
            )
        elif isinstance(ndattribute, NDAttributePv):
            ET.SubElement(
                root,
                "Attribute",
                name=ndattribute.name,
                type="EPICS_PV",
                source=ndattribute.signal.source.split("ca://")[-1],
                dbrtype=ndattribute.dbrtype.value,
                description=ndattribute.description,
            )
        else:
            raise ValueError(
                f"Invalid type for ndattributes: {type(ndattribute)}. "
                "Expected NDAttributePv or NDAttributeParam."
            )
    xml_text = ET.tostring(root, encoding="unicode")
    return xml_text
