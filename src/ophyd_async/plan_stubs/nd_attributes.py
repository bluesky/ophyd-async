from typing import Sequence
from xml.etree import cElementTree as ET

import bluesky.plan_stubs as bps

from ophyd_async.epics.areadetector.utils import (
    NDAttributeDataType,
    NDAttributeParam,
    NDAttributePv,
)
from ophyd_async.epics.areadetector.writers.nd_plugin import NDArrayBase, NDPluginStats


def setup_ndattributes(device: NDArrayBase,
                       ndattributes: Sequence[NDAttributePv | NDAttributeParam]):
    xml_text = ET.Element("Attributes")
    _dbr_types = {
        None: "DBR_NATIVE",
        NDAttributeDataType.INT: "DBR_LONG",
        NDAttributeDataType.DOUBLE: "DBR_DOUBLE",
        NDAttributeDataType.STRING: "DBR_STRING",
    }
    if isinstance(ndattributes,NDAttributeParam):
        ET.SubElement(
            xml_text,
            "Attribute",
            name=ndattributes.name,
            type="PARAM",
            source=ndattributes.param,
            addr=str(ndattributes.addr),
            datatype=_dbr_types[ndattributes.datatype],
            description=ndattributes.description,
        )
    elif isinstance(ndattributes,NDAttributePv):
        ET.SubElement(
            xml_text,
            "Attribute",
            name=ndattributes.name,
            type="EPICS_PV",
            source=ndattributes.signal.source,
            datatype=_dbr_types[ndattributes.datatype],
            description=ndattributes.description,
        )
    yield from bps.abs_set(device.nd_attributes_file, xml_text)

def setup_ndstats_sum(stats: NDPluginStats):
    pass
    #NDAttributeParam(name=f"{stats.parent.name}-sum", ...)
