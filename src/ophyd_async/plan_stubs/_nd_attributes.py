from collections.abc import Sequence
from xml.etree import ElementTree as ET

import bluesky.plan_stubs as bps

from ophyd_async.core import Device
from ophyd_async.epics.adcore import (
    NDArrayBaseIO,
    NDAttributeDataType,
    NDAttributeParam,
    NDAttributePv,
    NDFileHDFIO,
)


def setup_ndattributes(
    device: NDArrayBaseIO, ndattributes: Sequence[NDAttributePv | NDAttributeParam]
):
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
    yield from bps.abs_set(device.nd_attributes_file, xml_text, wait=True)


def setup_ndstats_sum(detector: Device):
    hdf = getattr(detector, "hdf", None)
    assert isinstance(hdf, NDFileHDFIO), (
        f"Expected {detector.name} to have 'hdf' attribute that is an NDFilHDFIO, "
        f"got {hdf}"
    )
    yield from (
        setup_ndattributes(
            hdf,
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
