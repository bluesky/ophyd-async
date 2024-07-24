from typing import Sequence
from xml.etree import cElementTree as ET

import bluesky.plan_stubs as bps

from ophyd_async.core._device import Device
from ophyd_async.epics.adcore._core_io import NDArrayBaseIO
from ophyd_async.epics.adcore._utils import (
    NDAttributeDataType,
    NDAttributeParam,
    NDAttributePv,
)


def setup_ndattributes(
    device: NDArrayBaseIO, ndattributes: Sequence[NDAttributePv | NDAttributeParam]
):
    xml_text = yield from bps.rd(device.nd_attributes_file)
    if xml_text == "":
        xml_text = ET.Element("Attributes")
    _dbr_types = {
        None: "DBR_NATIVE",
        NDAttributeDataType.INT: "DBR_LONG",
        NDAttributeDataType.DOUBLE: "DBR_DOUBLE",
        NDAttributeDataType.STRING: "DBR_STRING",
    }
    if isinstance(ndattributes, NDAttributeParam):
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
    elif isinstance(ndattributes, NDAttributePv):
        ET.SubElement(
            xml_text,
            "Attribute",
            name=ndattributes.name,
            type="EPICS_PV",
            source=ndattributes.signal.source,
            datatype=_dbr_types[ndattributes.datatype],
            description=ndattributes.description,
        )
    else:
        raise ValueError(
            f"Invalid type for ndattributes: {type(ndattributes)}. "
            "Expected NDAttributePv or NDAttributeParam."
        )
    yield from bps.mv(device.nd_attributes_file, xml_text)


def setup_ndstats_sum(detector: Device):
    yield from (
        setup_ndattributes(
            detector.hdf,
            NDAttributeParam(
                name=f"{detector.name}-sum",
                param="NDPluginStatsTotal",
                datatype=NDAttributeDataType.INT,
                description="Sum of the array",
            ),
        )
    )
