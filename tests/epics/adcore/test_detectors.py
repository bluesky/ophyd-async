import itertools
import os

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
            "shape": [10, 10],
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

    # If we are using the HDF writer, the uri will reference
    uri = str(path_info.directory_path) + "/"
    if writer_cls == adcore.ADHDFWriter:
        uri = uri.rstrip("/") + os.sep + f"{path_info.filename}.h5"
    test_det = ad_standard_det_factory(detector_cls, writer_cls=writer_cls)

    await test_det.stage()
    await test_det.prepare(one_shot_trigger_info)
    docs = [(name, doc) async for name, doc in test_det.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == test_det.name
    assert stream_resource["uri"] == "/".join(
        ["file://localhost", str(uri).lstrip("/")]
    )

    # Construct expected stream resource parameters based on writer
    expected_sres_params = {
        "chunk_shape": (1, 10, 10),
        "multiplier": 1,
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
            "shape": [10, 10],
            "dtype": "array",
            "dtype_numpy": "<u2",
            "external": "STREAM:",
        }
    }
