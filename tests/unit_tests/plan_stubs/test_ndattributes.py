from xml.etree import ElementTree as ET

import pytest

from ophyd_async.core import StaticPathProvider, init_devices
from ophyd_async.epics import adcore, adsimdetector
from ophyd_async.epics.core import epics_signal_r
from ophyd_async.plan_stubs import setup_ndattributes, setup_ndstats_sum


def test_setup_ndstats_raises_type_error(RE, static_path_provider: StaticPathProvider):
    with init_devices(mock=True):
        det = adsimdetector.sim_detector("PREFIX:", static_path_provider)
    with pytest.raises(
        AttributeError,
        match="det has no plugin named 'stats'",
    ):
        RE(setup_ndstats_sum(det))


async def test_nd_attributes_plan_stub(RE):
    async with init_devices(mock=True):
        stat = adcore.NDStatsIO("PREFIX:STATS:")
    param = adcore.NDAttributeParam(
        name="det-sum",
        param="sum",
        datatype=adcore.NDAttributeDataType.DOUBLE,
        description="Sum of det frame",
    )
    pv = adcore.NDAttributePv(
        name="Temperature",
        signal=epics_signal_r(str, "LINKAM:TEMP"),
        description="The sample temperature",
        dbrtype=adcore.NDAttributePvDbrType.DBR_FLOAT,
    )
    RE(setup_ndattributes(stat, [pv, param]))
    text = await stat.nd_attributes_file.get_value()
    xml = ET.fromstring(text)
    assert xml[0].tag == "Attribute"
    assert xml[0].attrib == {
        "name": "Temperature",
        "type": "EPICS_PV",
        "source": "LINKAM:TEMP",
        "dbrtype": "DBR_FLOAT",
        "description": "The sample temperature",
    }

    assert xml[1].tag == "Attribute"
    assert xml[1].attrib == {
        "name": "det-sum",
        "type": "PARAM",
        "source": "sum",
        "addr": "0",
        "datatype": "DOUBLE",
        "description": "Sum of det frame",
    }


@pytest.mark.parametrize("arg", [0.1, "string", 1, True, False])
async def test_nd_attributes_plan_stub_gives_correct_error(RE, arg):
    async with init_devices(mock=True):
        stat = adcore.NDStatsIO("PREFIX:STATS:")
    with pytest.raises(
        ValueError,
        match=f"Invalid type for ndattributes: {type(arg)}. "
        + "Expected NDAttributePv or NDAttributeParam.",
    ):
        RE(setup_ndattributes(stat, [arg]))
