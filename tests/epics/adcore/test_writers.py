from typing import List

import pytest

from ophyd_async.core import (
    DeviceCollector,
    PathProvider,
    ShapeProvider,
    StandardDetector,
    StaticPathProvider,
)
from ophyd_async.epics import adaravis, adcore, adkinetix, adpilatus, advimba
from ophyd_async.epics.signal._signal import epics_signal_r
from ophyd_async.plan_stubs._nd_attributes import setup_ndattributes, setup_ndstats_sum


class DummyShapeProvider(ShapeProvider):
    def __init__(self) -> None:
        pass

    async def __call__(self) -> tuple:
        return (10, 10, adcore.ADBaseDataType.UInt16)


@pytest.fixture
async def hdf_writer(
    RE, static_path_provider: StaticPathProvider
) -> adcore.ADHDFWriter:
    async with DeviceCollector(mock=True):
        hdf = adcore.NDFileHDFIO("HDF:")

    return adcore.ADHDFWriter(
        hdf,
        static_path_provider,
        lambda: "test",
        DummyShapeProvider(),
    )


@pytest.fixture
async def detectors(
    static_path_provider: PathProvider,
) -> List[StandardDetector]:
    detectors = []
    async with DeviceCollector(mock=True):
        detectors.append(advimba.VimbaDetector("VIMBA:", static_path_provider))
        detectors.append(adkinetix.KinetixDetector("KINETIX:", static_path_provider))
        detectors.append(adpilatus.PilatusDetector("PILATUS:", static_path_provider))
        detectors.append(adaravis.AravisDetector("ADARAVIS:", static_path_provider))
    return detectors


async def test_collect_stream_docs(hdf_writer: adcore.ADHDFWriter):
    assert hdf_writer._file is None

    [item async for item in hdf_writer.collect_stream_docs(1)]
    assert hdf_writer._file


async def test_stats_describe_when_plugin_configured_in_memory(RE, detectors):
    for detector in detectors:
        await detector.connect(mock=True)
        detector.set_name(type(detector).__name__)
        RE(setup_ndstats_sum(detector))
        xml = await detector.hdf.nd_attributes_file.get_value()
        for element in xml:
            assert str(element.tag) == "Attribute"
            assert (
                str(element.attrib)
                == f"{{'name': '{detector.name}-sum', 'type': 'PARAM', '"
                + "source': 'NDPluginStatsTotal', 'addr': '0', 'datatype': '<f4',"
                + " 'description': 'Sum of the array'}"
            )


async def test_nd_attributes_plan_stub(RE, detectors):
    for detector in detectors:
        await detector.connect(mock=True)
        detector.set_name(type(detector).__name__)
        param = adcore.NDAttributeParam(
            name=f"{detector.name}-sum",
            param="sum",
            datatype=adcore.NDAttributeDataType.DOUBLE,
            description=f"Sum of {detector.name} frame",
        )
        pv = adcore.NDAttributePv(
            name="Temperature",
            signal=epics_signal_r(str, "LINKAM:TEMP"),
            description="The sample temperature",
            datatype=adcore.NDAttributePvDataType.DBR_FLOAT,
        )
        RE(setup_ndattributes(detector.hdf, [pv, param]))
        xml = await detector.hdf.nd_attributes_file.get_value()
        assert str(xml[0].tag) == "Attribute"
        assert (
            str(xml[0].attrib)
            == "{'name': 'Temperature', 'type': 'EPICS_PV', '"
            + "source': 'ca://LINKAM:TEMP', 'datatype': '<f4',"
            + " 'description': 'The sample temperature'}"
        )
        assert str(xml[1].tag) == "Attribute"
        assert (
            str(xml[1].attrib)
            == f"{{'name': '{detector.name}-sum', 'type': 'PARAM', '"
            + "source': 'sum', 'addr': '0', 'datatype': '<f8',"
            + f" 'description': 'Sum of {detector.name} frame'}}"
        )


async def test_nd_attributes_plan_stub_gives_correct_error(RE, detectors):
    invalidObjects = [0.1, "string", 1, True, False]
    for detector in detectors:
        await detector.connect(mock=True)
        with pytest.raises(ValueError) as e:
            RE(setup_ndattributes(detector.hdf, invalidObjects))
        assert (
            str(e.value)
            == f"Invalid type for ndattributes: {type(invalidObjects[0])}. "
            + "Expected NDAttributePv or NDAttributeParam."
        )
