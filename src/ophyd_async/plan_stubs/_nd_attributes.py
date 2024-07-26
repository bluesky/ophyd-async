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
    xml_text = ET.Element("Attributes")

    for ndattribute in ndattributes:
        if isinstance(ndattribute, NDAttributeParam):
            ET.SubElement(
                xml_text,
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
                xml_text,
                "Attribute",
                name=ndattribute.name,
                type="EPICS_PV",
                source=ndattribute.signal.source,
                datatype=ndattribute.datatype.value,
                description=ndattribute.description,
            )
        else:
            raise ValueError(
                f"Invalid type for ndattributes: {type(ndattribute)}. "
                "Expected NDAttributePv or NDAttributeParam."
            )
    yield from bps.mv(device.nd_attributes_file, xml_text)


def setup_ndstats_sum(detector: Device):
    yield from (
        setup_ndattributes(
            detector.hdf,
            [
                NDAttributeParam(
                    name=f"{detector.name}-sum",
                    param="NDPluginStatsTotal",
                    datatype=NDAttributeDataType.DOUBLE,
                    description="Sum of the array",
                )
            ],
        )
    )
