import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest

from ophyd_async.core import (
    DatasetDescriber,
    PathProvider,
    StandardDetector,
    StaticPathProvider,
    init_devices,
)
from ophyd_async.epics import adaravis, adcore, adkinetix, adpilatus, advimba
from ophyd_async.epics.adpilatus import PilatusReadoutTime
from ophyd_async.epics.core import epics_signal_r
from ophyd_async.plan_stubs import setup_ndattributes, setup_ndstats_sum
from ophyd_async.testing import callback_on_mock_put, set_mock_value

DETECTOR_NAME = "test"


class DummyDatasetDescriber(DatasetDescriber):
    async def np_datatype(self) -> str:
        return "<u2"

    async def shape(self) -> tuple[int, int]:
        return (10, 10)


@pytest.fixture
async def hdf_writer(
    RE, static_path_provider: StaticPathProvider
) -> adcore.ADHDFWriter:
    async with init_devices(mock=True):
        hdf = adcore.NDFileHDFIO("HDF:")

    writer = adcore.ADHDFWriter(
        hdf,
        static_path_provider,
        DummyDatasetDescriber(),
        {},
    )

    def on_set_file_path_callback(value: str, wait: bool = True):
        """Mock a successful directory & file creation"""
        set_mock_value(writer.fileio.file_path_exists, True)
        set_mock_value(
            writer.fileio.full_file_name,
            f"{value}/{static_path_provider._filename_provider()}{writer._file_extension}",
        )

    callback_on_mock_put(writer.fileio.file_path, on_set_file_path_callback)

    return writer


@pytest.fixture
async def tiff_writer(
    RE, static_path_provider: StaticPathProvider
) -> adcore.ADTIFFWriter:
    async with init_devices(mock=True):
        tiff = adcore.NDFilePluginIO("TIFF:")

    writer = adcore.ADTIFFWriter(
        tiff, static_path_provider, DummyDatasetDescriber(), {}
    )

    def on_set_file_path_callback(value: str, wait: bool = True):
        """Mock a successful directory & file creation"""
        set_mock_value(writer.fileio.file_path_exists, True)
        set_mock_value(
            writer.fileio.full_file_name,
            f"{value}/{static_path_provider._filename_provider()}{writer._file_extension}",
        )

    callback_on_mock_put(writer.fileio.file_path, on_set_file_path_callback)

    return writer


@pytest.fixture
async def hdf_writer_with_stats(
    RE, static_path_provider: StaticPathProvider
) -> adcore.ADHDFWriter:
    async with init_devices(mock=True):
        hdf = adcore.NDFileHDFIO("HDF:")
        stats = adcore.NDPluginStatsIO("FOO:")

    # Set number of frames per chunk to something reasonable
    set_mock_value(hdf.num_frames_chunks, 2)

    writer = adcore.ADHDFWriter(
        hdf,
        static_path_provider,
        DummyDatasetDescriber(),
        {"stats": stats},
    )

    def on_set_file_path_callback(value: str, wait: bool = True):
        """Mock a successful directory & file creation"""
        set_mock_value(writer.fileio.file_path_exists, True)
        set_mock_value(
            writer.fileio.full_file_name,
            f"{value}/{static_path_provider._filename_provider()}{writer._file_extension}",
        )

    callback_on_mock_put(writer.fileio.file_path, on_set_file_path_callback)

    return writer


@pytest.fixture
async def detectors(
    static_path_provider: PathProvider,
) -> list[StandardDetector]:
    detectors = []
    async with init_devices(mock=True):
        detectors.append(advimba.VimbaDetector("VIMBA:", static_path_provider))
        detectors.append(adkinetix.KinetixDetector("KINETIX:", static_path_provider))
        detectors.append(
            adpilatus.PilatusDetector(
                "PILATUS:", static_path_provider, PilatusReadoutTime.PILATUS3
            )
        )
        detectors.append(adaravis.AravisDetector("ADARAVIS:", static_path_provider))
    return detectors


async def test_hdf_writer_file_not_found(hdf_writer: adcore.ADHDFWriter):
    callback_on_mock_put(hdf_writer.fileio.file_path, lambda value, wait: None)
    with pytest.raises(
        FileNotFoundError, match=r"Path .* doesn't exist or not writable!"
    ):
        await hdf_writer.open(DETECTOR_NAME)


async def test_hdf_writer_collect_stream_docs(hdf_writer: adcore.ADHDFWriter):
    assert hdf_writer._composer is None
    await hdf_writer.open("test", exposures_per_event=1)
    [item async for item in hdf_writer.collect_stream_docs(DETECTOR_NAME, 1)]

    assert hdf_writer._composer


async def test_tiff_writer_collect_stream_docs(tiff_writer: adcore.ADTIFFWriter):
    assert tiff_writer._emitted_resource is None
    await tiff_writer.open("test", exposures_per_event=1)
    [item async for item in tiff_writer.collect_stream_docs(DETECTOR_NAME, 1)]
    assert tiff_writer._emitted_resource


async def test_stats_describe_when_plugin_configured(
    hdf_writer_with_stats: adcore.ADHDFWriter,
):
    assert hdf_writer_with_stats._composer is None
    set_mock_value(hdf_writer_with_stats.fileio.file_path_exists, True)
    assert hdf_writer_with_stats._plugins is not None
    set_mock_value(
        hdf_writer_with_stats._plugins["stats"].nd_attributes_file,
        """<?xml version='1.0' encoding='utf-8'?>
<Attributes>
    <Attribute
        name="mydetector-sum"
        type="PARAM"
        source="TOTAL" addr="0"
        datatype="DOUBLE"
        description="Sum of each detector frame" />
    <Attribute
        name="mydetector-Temperature"
        type="EPICS_PV"
        source="LINKAM:TEMP"
        dbrtype="DBR_FLOAT"/>
</Attributes>
""",
    )
    with patch("ophyd_async.core._signal.wait_for_value", return_value=None):
        descriptor = await hdf_writer_with_stats.open(DETECTOR_NAME)

    assert descriptor == {
        "test": {
            "source": "mock+ca://HDF:FullFileName_RBV",
            "shape": [1, 10, 10],
            "dtype": "array",
            "dtype_numpy": "<u2",
            "external": "STREAM:",
        },
        "mydetector-sum": {
            "source": "mock+ca://HDF:FullFileName_RBV",
            "shape": [],
            "dtype": "number",
            "dtype_numpy": "<f8",
            "external": "STREAM:",
        },
        "mydetector-Temperature": {
            "dtype": "number",
            "dtype_numpy": "<f4",
            "external": "STREAM:",
            "shape": [],
            "source": "mock+ca://HDF:FullFileName_RBV",
        },
    }
    await hdf_writer_with_stats.close()


async def test_stats_describe_raises_error_with_dbr_native(
    hdf_writer_with_stats: adcore.ADHDFWriter,
):
    assert hdf_writer_with_stats._composer is None
    set_mock_value(hdf_writer_with_stats.fileio.file_path_exists, True)
    assert hdf_writer_with_stats._plugins is not None
    set_mock_value(
        hdf_writer_with_stats._plugins["stats"].nd_attributes_file,
        """<?xml version='1.0' encoding='utf-8'?>
<Attributes>
    <Attribute
        name="mydetector-Temperature"
        type="EPICS_PV"
        source="LINKAM:TEMP"
        dbrtype="DBR_NATIVE"/>
</Attributes>
""",
    )
    with pytest.raises(ValueError) as e:
        with patch("ophyd_async.core._signal.wait_for_value", return_value=None):
            await hdf_writer_with_stats.open(DETECTOR_NAME)
    await hdf_writer_with_stats.close()
    assert str(e.value) == "Don't support DBR_NATIVE yet"


async def test_stats_describe_when_plugin_configured_in_memory(RE, detectors):
    for detector in detectors:
        await detector.connect(mock=True)
        detector.set_name(type(detector).__name__)
        RE(setup_ndstats_sum(detector))
        xml = await detector.fileio.nd_attributes_file.get_value()
        root = ET.fromstring(xml)
        for element in root:
            assert str(element.tag) == "Attribute"
            assert element.attrib == {
                "name": f"{detector.name}-sum",
                "type": "PARAM",
                "source": "NDPluginStatsTotal",
                "addr": "0",
                "datatype": "DOUBLE",
                "description": "Sum of the array",
            }


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
            dbrtype=adcore.NDAttributePvDbrType.DBR_FLOAT,
        )
        RE(setup_ndattributes(detector.fileio, [pv, param]))
        text = await detector.fileio.nd_attributes_file.get_value()
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
            "name": f"{detector.name}-sum",
            "type": "PARAM",
            "source": "sum",
            "addr": "0",
            "datatype": "DOUBLE",
            "description": f"Sum of {detector.name} frame",
        }


async def test_nd_attributes_plan_stub_gives_correct_error(RE, detectors):
    invalidObjects = [0.1, "string", 1, True, False]
    for detector in detectors:
        await detector.connect(mock=True)
        with pytest.raises(ValueError) as e:
            RE(setup_ndattributes(detector.fileio, invalidObjects))
        assert (
            str(e.value)
            == f"Invalid type for ndattributes: {type(invalidObjects[0])}. "
            + "Expected NDAttributePv or NDAttributeParam."
        )


async def test_hdf_writer_descriptor_shape_contains_none(
    hdf_writer: adcore.ADHDFWriter,
):
    async def shape_containing_none():
        return 10, None, 10

    hdf_writer._dataset_describer.shape = shape_containing_none

    with pytest.raises(
        ValueError,
        match=r"Datasets with partially unknown dimensionality "
        r"are not currently supported by ADHDFWriter.",
    ):
        await hdf_writer.open(DETECTOR_NAME)
