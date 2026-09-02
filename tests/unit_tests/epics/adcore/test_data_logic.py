import os
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from unittest.mock import ANY, call

import pytest

from ophyd_async.core import (
    AutoIncrementingPathProvider,
    EnableDisable,
    StaticFilenameProvider,
    StaticPathProvider,
    TriggerInfo,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore, adsimdetector
from ophyd_async.epics.adcore import ADHDFDataLogic, NDArrayDescription
from ophyd_async.testing import assert_has_calls


@pytest.fixture
async def hdf_det(
    static_path_provider: StaticPathProvider,
) -> adcore.AreaDetector[adcore.ADBaseIO]:
    async with init_devices(mock=True):
        detector = adsimdetector.SimDetector(
            "PREFIX:",
            adcore.ADWriterFactory.hdf(static_path_provider),
            plugins={"stats": adcore.NDStatsIO("PREFIX:STATS:")},
        )
    set_mock_value(detector.driver.array_size_x, 1024)
    set_mock_value(detector.driver.array_size_y, 768)
    set_mock_value(detector.driver.data_type, adcore.ADBaseDataType.UINT16)
    return detector


async def test_make_data_provider_does_not_write(
    hdf_det: adcore.AreaDetector[adcore.ADBaseIO],
    static_path_provider: StaticPathProvider,
):
    """Describing the data must not open the file, since it may be discarded."""
    writer = hdf_det.get_plugin("hdf", adcore.NDFileHDF5IO)
    set_mock_value(writer.file_path_exists, True)
    logic = ADHDFDataLogic(
        array_description=NDArrayDescription(
            shape_signals=[hdf_det.driver.array_size_y, hdf_det.driver.array_size_x],
            data_type_signal=hdf_det.driver.data_type,
            color_mode_signal=hdf_det.driver.color_mode,
        ),
        path_provider=static_path_provider,
        driver=hdf_det.driver,
        writer=writer,
    )

    provider = await logic.make_data_provider("det", num_collections=5, period=0.1)
    assert provider is not None
    assert await writer.capture.get_value() is False
    assert await writer.file_name.get_value() == ""

    await logic.start()
    assert await writer.capture.get_value() is True
    assert await writer.file_name.get_value() != ""


@pytest.mark.parametrize(
    "enable_callbacks,plugin_enabled,makes_provider",
    [
        # The default switches the plugin on, whatever it was set to
        (True, EnableDisable.DISABLE, True),
        # Following the plugin, a disabled one writes nothing...
        (False, EnableDisable.DISABLE, False),
        # ...and an enabled one still writes
        (False, EnableDisable.ENABLE, True),
    ],
)
async def test_hdf_follows_the_plugin_when_not_enabling_it(
    hdf_det: adcore.AreaDetector[adcore.ADBaseIO],
    static_path_provider: StaticPathProvider,
    enable_callbacks: bool,
    plugin_enabled: EnableDisable,
    makes_provider: bool,
):
    writer = hdf_det.get_plugin("hdf", adcore.NDFileHDF5IO)
    set_mock_value(writer.file_path_exists, True)
    set_mock_value(writer.enable_callbacks, plugin_enabled)
    logic = ADHDFDataLogic(
        array_description=NDArrayDescription(
            shape_signals=[hdf_det.driver.array_size_y, hdf_det.driver.array_size_x],
            data_type_signal=hdf_det.driver.data_type,
            color_mode_signal=hdf_det.driver.color_mode,
        ),
        path_provider=static_path_provider,
        driver=hdf_det.driver,
        writer=writer,
        enable_callbacks=enable_callbacks,
    )

    provider = await logic.make_data_provider("det", num_collections=5, period=0.1)
    assert (provider is not None) is makes_provider

    if makes_provider:
        await logic.start()
        expected = EnableDisable.ENABLE if enable_callbacks else plugin_enabled
        assert await writer.enable_callbacks.get_value() is expected


async def test_hdf_writer_file_not_found(hdf_det: adcore.AreaDetector[adcore.ADBaseIO]):
    with pytest.raises(
        FileNotFoundError, match=r"Path .* doesn't exist or not writable!"
    ):
        await hdf_det.prepare(TriggerInfo())


async def test_hdf_writer_passes_parent_name_to_path_provider(tmp_path: Path):
    pp = AutoIncrementingPathProvider(
        StaticFilenameProvider("test"), tmp_path, max_digits=3
    )
    async with init_devices(mock=True):
        det = adsimdetector.SimDetector(
            "PREFIX:", adcore.ADWriterFactory.hdf(pp), name="sim_detector"
        )

    writer = det.get_plugin("hdf", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    await det.stage()
    await det.prepare(TriggerInfo())
    assert (
        await writer.file_path.get_value()
        == str(tmp_path) + os.sep + "sim_detector_000" + os.sep
    )


async def test_prepare_hdf(
    static_path_provider: StaticPathProvider,
    hdf_det: adcore.AreaDetector[adcore.ADBaseIO],
):
    writer = hdf_det.get_plugin("hdf", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    await hdf_det.prepare(TriggerInfo(number_of_events=3))
    assert_has_calls(
        hdf_det,
        [
            # From prepare
            call.driver.image_mode.put(adcore.ADImageMode.MULTIPLE),
            call.driver.num_images.put(3),
            call.hdf.num_frames_chunks.put(1),
            call.hdf.chunk_size_auto.put(True),
            call.hdf.num_extra_dims.put(0),
            call.hdf.lazy_open.put(True),
            call.hdf.swmr_mode.put(True),
            call.hdf.xml_file_name.put(""),
            call.hdf.enable_callbacks.put(EnableDisable.ENABLE),
            call.hdf.create_directory.put(0),
            call.hdf.file_path.put(f"{static_path_provider().directory_path}{os.sep}"),
            call.hdf.file_name.put("ophyd_async_tests"),
            call.hdf.file_template.put("%s%s.h5"),
            call.hdf.auto_increment.put(True),
            call.hdf.file_number.put(0),
            call.hdf.file_write_mode.put(adcore.ADFileWriteMode.STREAM),
            call.hdf.num_capture.put(0),
            call.hdf.capture.put(True),
        ],
    )


@pytest.mark.parametrize(
    "flush_period,livetime,deadtime,expected_frames_per_chunk",
    [
        # 0.5s flush / 0.01s period -> 50 frames per chunk (#1309)
        (0.5, 0.01, 0.0, 50),
        # 0.5s flush / 0.05s period -> 10 frames per chunk
        (0.5, 0.04, 0.01, 10),
        # A sub-frame flush period floors to a single frame per chunk
        (0.001, 0.05, 0.0, 1),
    ],
)
async def test_hdf_chunk_sized_from_flush_period(
    static_path_provider: StaticPathProvider,
    flush_period: float,
    livetime: float,
    deadtime: float,
    expected_frames_per_chunk: int,
):
    """A configured flush_period sizes the HDF chunk from the frame period."""
    async with init_devices(mock=True):
        det = adsimdetector.SimDetector(
            "PREFIX:",
            adcore.ADWriterFactory.hdf(static_path_provider, flush_period=flush_period),
        )
    set_mock_value(det.driver.array_size_x, 1024)
    set_mock_value(det.driver.array_size_y, 768)
    set_mock_value(det.driver.data_type, adcore.ADBaseDataType.UINT16)
    writer = det.get_plugin("hdf", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    await det.prepare(
        TriggerInfo(livetime=livetime, deadtime=deadtime, number_of_events=3)
    )
    assert await writer.num_frames_chunks.get_value() == expected_frames_per_chunk
    (sr, *_) = [doc async for doc in det.collect_asset_docs(3)]
    assert sr[1]["parameters"]["chunk_shape"] == (
        expected_frames_per_chunk,
        768,
        1024,
    )


@pytest.mark.parametrize(
    "factory_cls,is_hdf",
    [
        (adcore.ADWriterFactory.hdf, True),
        (adcore.ADWriterFactory.jpeg, False),
        (adcore.ADWriterFactory.tiff, False),
    ],
)
async def test_can_specify_different_uri_and_path(
    tmp_path: Path,
    factory_cls,
    is_hdf: bool,
):
    # Create a static path provider that will return a specific directory
    expected_uri = f"file://nfs-share-host{tmp_path.absolute().as_posix()}/different/"
    path_provider = StaticPathProvider(
        StaticFilenameProvider("test"), tmp_path, directory_uri=expected_uri
    )
    path_info = path_provider()

    async with init_devices(mock=True):
        det = adsimdetector.SimDetector("PREFIX:", factory_cls(path_provider))
    writer = det.get_plugin(factory_cls.__name__, adcore.NDPluginFileIO)
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
    if is_hdf:
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
@pytest.mark.parametrize(
    "factory_cls,is_hdf",
    [
        (adcore.ADWriterFactory.hdf, True),
        (adcore.ADWriterFactory.jpeg, False),
        (adcore.ADWriterFactory.tiff, False),
    ],
)
async def test_can_override_uri_with_different_path_semantics(
    expected_separator: str,
    write_path: PurePath,
    factory_cls,
    is_hdf: bool,
):
    expected_uri = "file://nfs-share/something/"
    path_provider = StaticPathProvider(
        StaticFilenameProvider("test"), write_path, directory_uri=expected_uri
    )
    path_info = path_provider()

    async with init_devices(mock=True):
        det = adsimdetector.SimDetector("PREFIX:", factory_cls(path_provider))
    writer = det.get_plugin(factory_cls.__name__, adcore.NDPluginFileIO)
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
    if is_hdf:
        expected_uri += path_info.filename + ".h5"

    assert stream_resource["uri"] == expected_uri


async def test_stats_describe_raises_error_with_dbr_native(
    hdf_det: adcore.AreaDetector[adcore.ADBaseIO],
):
    stats = hdf_det.get_plugin("stats")
    writer = hdf_det.get_plugin("hdf", adcore.NDPluginFileIO)
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


@pytest.mark.parametrize(
    "color_mode,shape",
    [
        (adcore.ADBaseColorMode.MONO, [1, 768, 1024]),
        (adcore.ADBaseColorMode.BAYER, RuntimeError),
        (adcore.ADBaseColorMode.RGB1, [1, 3, 768, 1024]),
        (adcore.ADBaseColorMode.RGB2, RuntimeError),
        (adcore.ADBaseColorMode.RGB3, RuntimeError),
        (adcore.ADBaseColorMode.YUV444, RuntimeError),
        (adcore.ADBaseColorMode.YUV422, RuntimeError),
        (adcore.ADBaseColorMode.YUV421, RuntimeError),
    ],
)
async def test_describe_different_color_modes(
    hdf_det: adcore.AreaDetector[adcore.ADBaseIO],
    color_mode: adcore.ADBaseColorMode,
    shape: list[int] | type[RuntimeError],
):
    writer = hdf_det.get_plugin("hdf", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    set_mock_value(hdf_det.driver.color_mode, color_mode)
    if shape is RuntimeError:
        # Expected to fail for this mode
        with pytest.raises(
            RuntimeError,
            match=f"Unsupported ColorMode {color_mode.value}!"
            " Only Mono and RGB1 are supported.",
        ):
            await hdf_det.prepare(TriggerInfo())
    else:
        # Expected to give the right shape in the descriptor
        await hdf_det.prepare(TriggerInfo())
        describe = await hdf_det.describe()
        assert describe["detector"] == {
            "dtype": "array",
            "dtype_numpy": "<u2",
            "external": "STREAM:",
            "shape": shape,
            "source": ANY,
        }


async def test_3d_dataset_shape(hdf_det: adcore.AreaDetector[adcore.ADBaseIO]):
    writer = hdf_det.get_plugin("hdf", adcore.NDPluginFileIO)
    set_mock_value(writer.file_path_exists, True)
    set_mock_value(hdf_det.driver.array_size_z, 10)
    await hdf_det.prepare(TriggerInfo())
    describe = await hdf_det.describe()
    assert describe["detector"] == {
        "dtype": "array",
        "dtype_numpy": "<u2",
        "external": "STREAM:",
        "shape": [1, 10, 768, 1024],
        "source": ANY,
    }
