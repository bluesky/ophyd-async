import random
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from ophyd_async.core import (
    DeviceCollector,
    PathProvider,
    ShapeProvider,
    StandardDetector,
    StaticPathProvider,
    set_mock_value,
)
from ophyd_async.epics import adaravis, adcore, adkinetix, adpilatus, advimba
from ophyd_async.epics.adcore._hdf_writer import ADHDFWriter
from ophyd_async.epics.signal._signal import epics_signal_r
from ophyd_async.plan_stubs.nd_attributes import setup_ndattributes, setup_ndstats_sum


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
        name_provider=lambda: "test",
        shape_provider=DummyShapeProvider(),
    )


@pytest.fixture
async def hdf_writer_with_stats(
    RE, static_path_provider: StaticPathProvider
) -> ADHDFWriter:
    async with DeviceCollector(mock=True):
        hdf = adcore.NDFileHDFIO("HDF:")
        stats = adcore.NDPluginStatsIO("FOO:")

    return ADHDFWriter(
        hdf,
        static_path_provider,
        name_provider=lambda: "test",
        shape_provider=DummyShapeProvider(),
        plugins=[stats],
    )


@pytest.fixture
async def stats_sum_enabled_xml(tmp_path: Path) -> Path:
    stats_path = tmp_path / "stats.xml"
    stats_path.write_text("""<?xml version='1.0' encoding='utf-8'?>
<Attributes>
    <Attribute name="StatsTotal" type="PARAM" source="TOTAL" addr="0" datatype="DOUBLE"
                           description="Sum of each detector frame" />
</Attributes>""")
    return stats_path


@pytest.fixture
async def invalid_xml(tmp_path: Path) -> Path:
    stats_path = tmp_path / "stats.xml"
    stats_path.write_text("Invalid XML")
    return stats_path


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


async def test_correct_descriptor_doc_after_open(hdf_writer: adcore.ADHDFWriter):
    set_mock_value(hdf_writer.hdf.file_path_exists, True)
    with patch("ophyd_async.core._signal.wait_for_value", return_value=None):
        descriptor = await hdf_writer.open()

    assert descriptor == {
        "test": {
            "source": "mock+ca://HDF:FullFileName_RBV",
            "shape": (10, 10),
            "dtype": "array",
            "dtype_numpy": "<u2",
            "external": "STREAM:",
        }
    }

    await hdf_writer.close()


async def test_collect_stream_docs(hdf_writer: adcore.ADHDFWriter):
    assert hdf_writer._file is None

    [item async for item in hdf_writer.collect_stream_docs(1)]
    assert hdf_writer._file


async def test_stats_describe_when_plugin_configured(
    hdf_writer_with_stats: ADHDFWriter, stats_sum_enabled_xml: Path
):
    assert hdf_writer_with_stats._file is None
    set_mock_value(hdf_writer_with_stats.hdf.file_path_exists, True)
    set_mock_value(
        hdf_writer_with_stats._plugins[0].nd_attributes_file,
        str(stats_sum_enabled_xml),
    )
    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
        descriptor = await hdf_writer_with_stats.open()

    assert descriptor == {
        "test": {
            "source": "mock+ca://HDF:FullFileName_RBV",
            "shape": (10, 10),
            "dtype": "array",
            "dtype_numpy": "<u2",
            "external": "STREAM:",
        },
        "StatsTotal": {
            "source": "mock+ca://HDF:FullFileName_RBV",
            "shape": (),
            "dtype": "number",
            "dtype_numpy": "d",
            "external": "STREAM:",
        },
    }
    await hdf_writer_with_stats.close()


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
                + "source': 'NDPluginStatsTotal', 'addr': '0', 'datatype': 'DBR_LONG',"
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
        )
        RE(setup_ndattributes(detector.hdf, pv))
        RE(setup_ndattributes(detector.hdf, param))
        xml = await detector.hdf.nd_attributes_file.get_value()
        assert str(xml[0].tag) == "Attribute"
        assert (
            str(xml[0].attrib)
            == "{'name': 'Temperature', 'type': 'EPICS_PV', '"
            + "source': 'ca://LINKAM:TEMP', 'datatype': 'DBR_NATIVE',"
            + " 'description': 'The sample temperature'}"
        )
        assert str(xml[1].tag) == "Attribute"
        assert (
            str(xml[1].attrib)
            == f"{{'name': '{detector.name}-sum', 'type': 'PARAM', '"
            + "source': 'sum', 'addr': '0', 'datatype': 'DBR_DOUBLE',"
            + f" 'description': 'Sum of {detector.name} frame'}}"
        )


async def test_nd_attributes_plan_stub_gives_correct_error(RE, detectors):
    invalidObjects = [0.1, "string", 1, True, False]
    for detector in detectors:
        await detector.connect(mock=True)
        arg = random.choice(invalidObjects)
        with pytest.raises(ValueError) as e:
            RE(setup_ndattributes(detector.hdf, arg))
        assert (
            str(e.value)
            == f"Invalid type for ndattributes: {type(arg)}. "
            + "Expected NDAttributePv or NDAttributeParam."
        )


async def test_invalid_xml_raises_error(
    hdf_writer_with_stats: ADHDFWriter, invalid_xml: Path
):
    assert hdf_writer_with_stats._file is None
    set_mock_value(hdf_writer_with_stats.hdf.file_path_exists, True)
    set_mock_value(
        hdf_writer_with_stats._plugins[0].nd_attributes_file,
        str(invalid_xml),
    )
    with pytest.raises(Exception) as e:
        with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
            descriptor = await hdf_writer_with_stats.open()
    assert str(e.value) == "Error parsing XML"
    await hdf_writer_with_stats.close()
