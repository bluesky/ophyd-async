import itertools
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import pytest

from ophyd_async.core import StaticPathProvider, TriggerInfo
from ophyd_async.epics import (
    adandor,
    adaravis,
    adcore,
    adkinetix,
    adpilatus,
    adsimdetector,
    advimba,
)

DETECTOR_CLASSES: list[type[adcore.AreaDetector]] = [
    adsimdetector.SimDetector,
    advimba.VimbaDetector,
    adandor.Andor2Detector,
    adaravis.AravisDetector,
    adkinetix.KinetixDetector,
    adpilatus.PilatusDetector,
    adcore.ContAcqAreaDetector,
]

WRITER_CLASSES: list[type[adcore.ADWriter]] = [
    adcore.ADHDFWriter,
    adcore.ADTIFFWriter,
    adcore.ADJPEGWriter,
]

pytestmark = pytest.mark.parametrize(
    "detector_cls, writer_cls",
    list(itertools.product(DETECTOR_CLASSES, WRITER_CLASSES)),
)


async def test_hints_from_hdf_writer(
    ad_standard_det_factory,
    detector_cls: type[adcore.AreaDetector],
    writer_cls: type[adcore.ADWriter],
):
    test_det = ad_standard_det_factory(detector_cls, writer_cls=writer_cls)
    assert test_det.hints == {"fields": [test_det.name]}


async def test_can_read(
    ad_standard_det_factory,
    detector_cls: type[adcore.AreaDetector],
    writer_cls: type[adcore.ADWriter],
):
    # Standard detector can be used as Readable
    test_det = ad_standard_det_factory(detector_cls, writer_cls=writer_cls)
    assert (await test_det.read()) == {}


async def test_describes_writer_dataset(
    ad_standard_det_factory,
    detector_cls: type[adcore.AreaDetector],
    writer_cls: type[adcore.ADWriter],
    one_shot_trigger_info: TriggerInfo,
):
    test_det = ad_standard_det_factory(detector_cls, writer_cls=writer_cls)
    assert await test_det.describe() == {}
    await test_det.stage()
    await test_det.prepare(one_shot_trigger_info)
    assert await test_det.describe() == {
        f"{test_det.name}": {
            "source": (
                f"mock+ca://{detector_cls.__name__[: -len('Detector')].upper()}"
                f"1:{writer_cls.default_suffix}FullFileName_RBV"
            ),
            "shape": [one_shot_trigger_info.exposures_per_event, 10, 10],
            "dtype": "array",
            "dtype_numpy": "<u2",
            "external": "STREAM:",
        }
    }


async def test_can_collect(
    ad_standard_det_factory,
    detector_cls: type[adcore.AreaDetector],
    writer_cls: type[adcore.ADWriter],
    static_path_provider: StaticPathProvider,
    one_shot_trigger_info: TriggerInfo,
):
    path_info = static_path_provider()

    test_det = ad_standard_det_factory(detector_cls, writer_cls=writer_cls)

    await test_det.stage()
    await test_det.prepare(one_shot_trigger_info)
    docs = [(name, doc) async for name, doc in test_det.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == test_det.name

    # With HDF writer, the URI points directly to the file. For other writers, since a
    # dataset is many files, point to the directory instead.
    expected_uri = (
        "file://localhost/"
        + path_info.directory_path.absolute().as_posix().lstrip("/")
        + "/"
    )
    if writer_cls == adcore.ADHDFWriter:
        expected_uri += path_info.filename + ".h5"

    assert stream_resource["uri"] == expected_uri

    # Construct expected stream resource parameters based on writer
    expected_sres_params: dict[str, Any] = {
        "chunk_shape": (1, 10, 10),
    }
    if writer_cls == adcore.ADHDFWriter:
        expected_sres_params["dataset"] = "/entry/data/data"
    else:
        expected_sres_params["template"] = (
            "ophyd_async_tests_{:06d}" + test_det._writer._file_extension
        )

    assert stream_resource["parameters"] == expected_sres_params
    assert docs[1][0] == "stream_datum"
    stream_datum = docs[1][1]
    assert stream_datum["stream_resource"] == sr_uid
    assert stream_datum["seq_nums"] == {"start": 0, "stop": 0}
    assert stream_datum["indices"] == {"start": 0, "stop": 1}


async def test_can_specify_different_uri_and_path(
    ad_standard_det_factory,
    detector_cls: type[adcore.AreaDetector],
    writer_cls: type[adcore.ADWriter],
    one_shot_trigger_info: TriggerInfo,
    tmp_path: Path,
    static_path_provider_factory,
    static_filename_provider,
):
    # Create a static path provider that will return a specific directory
    expected_uri = f"file://localhost/{tmp_path.absolute().as_posix()}/different/"
    path_provider = static_path_provider_factory(
        static_filename_provider, directory_uri=expected_uri
    )
    test_det = ad_standard_det_factory(
        detector_cls, writer_cls=writer_cls, path_provider=path_provider
    )

    path_info = test_det._writer._path_provider(device_name=test_det.name)

    await test_det.stage()
    await test_det.prepare(one_shot_trigger_info)
    docs = [(name, doc) async for name, doc in test_det.collect_asset_docs(1)]

    # Make sure we set the write path to the directory_path attr from our path info
    assert await test_det.fileio.file_path.get_value() == str(tmp_path) + os.sep

    # Then, check to make sure our resource doc uses the overridden URI
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]

    # With HDF writer, the URI points directly to the file. For other writers, since a
    # dataset is many files, point to the directory instead.
    if writer_cls == adcore.ADHDFWriter:
        expected_uri += path_info.filename + ".h5"

    assert stream_resource["uri"] == expected_uri


@pytest.mark.parametrize("write_path_format", [PurePosixPath, PureWindowsPath])
async def test_can_override_uri_with_different_path_semantics(
    write_path_format,
    ad_standard_det_factory,
    detector_cls: type[adcore.AreaDetector],
    writer_cls: type[adcore.ADWriter],
    one_shot_trigger_info: TriggerInfo,
    static_filename_provider,
):
    windows_path = PureWindowsPath(
        "C:\\Users\\test\\AppData\\Local\\Temp\\ophyd_async_tests"
    )
    posix_path = PurePosixPath("/tmp/ophyd_async_tests")

    if write_path_format is PureWindowsPath:
        write_path = windows_path
        expected_uri = f"file://localhost/{posix_path.as_posix().lstrip('/')}/"
    else:
        write_path = posix_path
        expected_uri = f"file://localhost/{windows_path.as_posix().lstrip('/')}/"

    path_provider = StaticPathProvider(
        static_filename_provider, write_path, directory_uri=expected_uri
    )

    test_det = ad_standard_det_factory(
        detector_cls,
        writer_cls=writer_cls,
        path_provider=path_provider,
        assume_file_path_exists=True,
    )

    path_info = test_det._writer._path_provider(device_name=test_det.name)
    await test_det.stage()
    await test_det.prepare(one_shot_trigger_info)
    docs = [(name, doc) async for name, doc in test_det.collect_asset_docs(1)]
    if write_path_format is PureWindowsPath:
        assert await test_det.fileio.file_path.get_value() == f"{windows_path}\\"
    else:
        assert await test_det.fileio.file_path.get_value() == f"{posix_path}/"
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]

    # With HDF writer, the URI points directly to the file. For other writers, since a
    # dataset is many files, point to the directory instead.
    if writer_cls == adcore.ADHDFWriter:
        expected_uri += path_info.filename + ".h5"

    assert stream_resource["uri"] == expected_uri


async def test_can_decribe_collect(
    ad_standard_det_factory,
    detector_cls: type[adcore.AreaDetector],
    writer_cls: type[adcore.ADWriter],
    one_shot_trigger_info: TriggerInfo,
):
    test_det = ad_standard_det_factory(detector_cls, writer_cls=writer_cls)

    assert (await test_det.describe_collect()) == {}
    await test_det.stage()
    await test_det.prepare(one_shot_trigger_info)
    assert (await test_det.describe_collect()) == {
        f"{test_det.name}": {
            "source": (
                f"mock+ca://{detector_cls.__name__[: -len('Detector')].upper()}"
                f"1:{writer_cls.default_suffix}FullFileName_RBV"
            ),
            "shape": [one_shot_trigger_info.exposures_per_event, 10, 10],
            "dtype": "array",
            "dtype_numpy": "<u2",
            "external": "STREAM:",
        }
    }
