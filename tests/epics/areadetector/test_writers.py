from pathlib import Path
from unittest.mock import patch

import pytest

from ophyd_async.core import (
    DeviceCollector,
    ShapeProvider,
    StaticPathProvider,
    set_mock_value,
)
from ophyd_async.epics.areadetector.writers import ADBaseDataType, HDFWriter, NDFileHDF
from ophyd_async.epics.areadetector.writers.nd_plugin import NDPluginStats


class DummyShapeProvider(ShapeProvider):
    def __init__(self) -> None:
        pass

    async def __call__(self) -> tuple:
        return (10, 10, ADBaseDataType.UInt16)


@pytest.fixture
async def hdf_writer(RE, static_path_provider: StaticPathProvider) -> HDFWriter:
    async with DeviceCollector(mock=True):
        hdf = NDFileHDF("HDF:")

    return HDFWriter(
        hdf,
        static_path_provider,
        name_provider=lambda: "test",
        shape_provider=DummyShapeProvider(),
    )


@pytest.fixture
async def hdf_writer_with_stats(
    RE, static_path_provider: StaticPathProvider
) -> HDFWriter:
    async with DeviceCollector(mock=True):
        hdf = NDFileHDF("HDF:")
        stats = NDPluginStats("FOO:")

    return HDFWriter(
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


async def test_correct_descriptor_doc_after_open(hdf_writer: HDFWriter):
    set_mock_value(hdf_writer.hdf.file_path_exists, True)
    with patch("ophyd_async.core.signal.wait_for_value", return_value=None):
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


async def test_collect_stream_docs(hdf_writer: HDFWriter):
    assert hdf_writer._file is None

    [item async for item in hdf_writer.collect_stream_docs(1)]
    assert hdf_writer._file


async def test_stats_describe_when_plugin_configured(
    hdf_writer_with_stats: HDFWriter, stats_sum_enabled_xml: Path
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
        "Attribute-{'name': 'StatsTotal', 'type': 'PARAM', 'source': 'TOTAL', 'addr': '0', 'datatype': 'DOUBLE', 'description': 'Sum of each detector frame'}": {  # noqa: E501
            "source": "mock+ca://HDF:FullFileName_RBV",
            "shape": (),
            "dtype": "number",
            "dtype_numpy": "",
            "external": "STREAM:",
        },
    }
    await hdf_writer_with_stats.close()
