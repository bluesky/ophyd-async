from ophyd_async.epics import adcore


def test_ndattribute_writing_xml():
    xml = adcore.NDAttributesXML()
    xml.add_epics_pv("Temperature", "LINKAM:TEMP", description="The sample temperature")
    xml.add_param(
        "STATS_SUM",
        "SUM",
        adcore.NDAttributeDataType.DOUBLE,
        description="Sum of pilatus frame",
    )
    actual = str(xml)
    expected = """<?xml version='1.0' encoding='utf-8'?>
<Attributes>
    <Attribute name="Temperature" type="EPICS_PV" source="LINKAM:TEMP" datatype="DBR_NATIVE" description="The sample temperature" />
    <Attribute name="STATS_SUM" type="PARAM" source="SUM" addr="0" datatype="DOUBLE" description="Sum of pilatus frame" />
</Attributes>"""  # noqa: E501
    assert actual == expected
