import os
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from unittest.mock import call

import pytest

from ophyd_async.core import (
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
    get_mock,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore, adsimdetector


@pytest.fixture
async def hdf_det(
    static_path_provider: StaticPathProvider,
) -> adcore.AreaDetector[adcore.ADBaseIO]:
    async with init_devices(mock=True):
        detector = adsimdetector.sim_detector(
            "PREFIX:",
            static_path_provider,
            plugins={"stats": adcore.NDStatsIO("PREFIX:STATS:")},
        )
    set_mock_value(detector.driver.array_size_x, 1024)
    set_mock_value(detector.driver.array_size_y, 768)
    set_mock_value(detector.driver.data_type, adcore.ADBaseDataType.UINT16)
    return detector


async def test_hdf_writer_file_not_found(hdf_det: adcore.AreaDetector[adcore.ADBaseIO]):
    with pytest.raises(
        FileNotFoundError, match=r"Path .* doesn't exist or not writable!"
    ):
        await hdf_det.prepare(TriggerInfo())


async def test_prepare_hdf(
    static_path_provider: StaticPathProvider,
    hdf_det: adcore.AreaDetector[adcore.ADBaseIO],
):
    writer = hdf_det.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    await hdf_det.prepare(TriggerInfo(number_of_events=3))
    assert list(get_mock(hdf_det).mock_calls) == [
        # From prepare
        call.driver.image_mode.put(adcore.ADImageMode.MULTIPLE, wait=True),
        call.driver.num_images.put(3, wait=True),
        call.writer.num_frames_chunks.put(1, wait=True),
        call.writer.chunk_size_auto.put(True, wait=True),
        call.writer.num_extra_dims.put(0, wait=True),
        call.writer.lazy_open.put(True, wait=True),
        call.writer.swmr_mode.put(True, wait=True),
        call.writer.xml_file_name.put("", wait=True),
        call.writer.create_directory.put(0, wait=True),
        call.writer.file_path.put(
            f"{static_path_provider().directory_path}/", wait=True
        ),
        call.writer.file_name.put("ophyd_async_tests", wait=True),
        call.writer.file_template.put("%s%s.h5", wait=True),
        call.writer.auto_increment.put(True, wait=True),
        call.writer.file_number.put(0, wait=True),
        call.writer.file_write_mode.put(adcore.ADFileWriteMode.STREAM, wait=True),
        call.writer.num_capture.put(0, wait=True),
        call.writer.capture.put(True, wait=True),
    ]


@pytest.mark.parametrize("writer_type", adcore.ADWriterType.__members__.values())
async def test_can_specify_different_uri_and_path(
    tmp_path: Path,
    writer_type: adcore.ADWriterType,
):
    # Create a static path provider that will return a specific directory
    expected_uri = f"file://nfs-share-host{tmp_path.absolute().as_posix()}/different/"
    path_provider = StaticPathProvider(
        StaticFilenameProvider("test"), tmp_path, directory_uri=expected_uri
    )
    path_info = path_provider()

    async with init_devices(mock=True):
        det = adsimdetector.sim_detector(
            "PREFIX:", path_provider, writer_type=writer_type
        )
    writer = det.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    await det.stage()
    await det.prepare(TriggerInfo())
    docs = [doc async for doc in det.collect_asset_docs(1)]

    # Make sure we set the write path to the directory_path attr from our path info
    assert await writer.file_path.get_value() == str(tmp_path) + os.sep

    # Then, check to make sure our resource doc uses the overridden URI
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]

    # With HDF writer, the URI points directly to the file. For other writers, since a
    # dataset is many files, point to the directory instead.
    if writer_type == adcore.ADWriterType.HDF:
        expected_uri += path_info.filename + ".h5"

    assert stream_resource["uri"] == expected_uri


@pytest.mark.parametrize(
    "expected_separator,write_path",
    [
        (
            "\\",
            PureWindowsPath("C:\\Users\\test\\AppData\\Local\\Temp\\ophyd_async_tests"),
        ),
        (
            "/",
            PurePosixPath("/tmp/ophyd_async_tests"),
        ),
    ],
)
@pytest.mark.parametrize("writer_type", adcore.ADWriterType.__members__.values())
async def test_can_override_uri_with_different_path_semantics(
    expected_separator: str,
    write_path: PurePath,
    writer_type: adcore.ADWriterType,
):
    expected_uri = "file://nfs-share/something/"
    path_provider = StaticPathProvider(
        StaticFilenameProvider("test"), write_path, directory_uri=expected_uri
    )
    path_info = path_provider()

    async with init_devices(mock=True):
        det = adsimdetector.sim_detector(
            "PREFIX:", path_provider, writer_type=writer_type
        )
    writer = det.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    await det.stage()
    await det.prepare(TriggerInfo())
    docs = [doc async for doc in det.collect_asset_docs(1)]

    assert await writer.file_path.get_value() == f"{write_path}{expected_separator}"
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]

    # With HDF writer, the URI points directly to the file. For other writers, since a
    # dataset is many files, point to the directory instead.
    if writer_type == adcore.ADWriterType.HDF:
        expected_uri += path_info.filename + ".h5"

    assert stream_resource["uri"] == expected_uri


async def test_stats_describe_raises_error_with_dbr_native(
    hdf_det: adcore.AreaDetector[adcore.ADBaseIO],
):
    stats = hdf_det.get_plugin("stats")
    writer = hdf_det.get_plugin("writer", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    set_mock_value(
        stats.nd_attributes_file,
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
    with pytest.raises(
        RuntimeError,
        match="NDAttribute mydetector-Temperature has dbrtype DBR_NATIVE,"
        " which is not supported",
    ):
        await hdf_det.trigger()
