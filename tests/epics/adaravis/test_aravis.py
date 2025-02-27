from unittest.mock import AsyncMock, patch

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    PathProvider,
    TriggerInfo,
)
from ophyd_async.epics import adaravis


@pytest.fixture
def test_adaravis(ad_standard_det_factory) -> adaravis.AravisDetector:
    return ad_standard_det_factory(adaravis.AravisDetector)


@pytest.mark.parametrize("exposure_time", [0.0, 0.1, 1.0, 10.0, 100.0])
async def test_deadtime_invariant_with_exposure_time(
    exposure_time: float,
    test_adaravis: adaravis.AravisDetector,
):
    assert test_adaravis._controller.get_deadtime(exposure_time) == 1961e-6


async def test_hints_from_hdf_writer(test_adaravis: adaravis.AravisDetector):
    assert test_adaravis.hints == {"fields": ["test_adaravis1"]}


async def test_can_read(test_adaravis: adaravis.AravisDetector):
    # Standard detector can be used as Readable
    assert (await test_adaravis.read()) == {}


@pytest.mark.parametrize("one_shot_trigger_info", [1, 2, 10, 100], indirect=True)
async def test_decribe_describes_writer_dataset(
    test_adaravis: adaravis.AravisDetector, one_shot_trigger_info: TriggerInfo
):
    assert await test_adaravis.describe() == {}
    await test_adaravis.stage()
    await test_adaravis.prepare(one_shot_trigger_info)
    assert await test_adaravis.describe() == {
        "test_adaravis1": {
            "source": "mock+ca://ARAVIS1:HDF1:FullFileName_RBV",
            "shape": [one_shot_trigger_info.exposures_per_event, 10, 10],
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }


@pytest.mark.parametrize("one_shot_trigger_info", [1, 2, 10, 100], indirect=True)
async def test_can_collect(
    test_adaravis: adaravis.AravisDetector,
    static_path_provider: PathProvider,
    one_shot_trigger_info: TriggerInfo,
):
    path_info = static_path_provider()
    full_file_name = path_info.directory_path / f"{path_info.filename}.h5"
    await test_adaravis.stage()
    await test_adaravis.prepare(one_shot_trigger_info)
    docs = [(name, doc) async for name, doc in test_adaravis.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "test_adaravis1"
    assert stream_resource["uri"] == "file://localhost/" + str(full_file_name).lstrip(
        "/"
    )
    assert stream_resource["parameters"] == {
        "dataset": "/entry/data/data",
        "swmr": False,
        "chunk_shape": (1, 10, 10),
    }
    assert docs[1][0] == "stream_datum"
    stream_datum = docs[1][1]
    assert stream_datum["stream_resource"] == sr_uid
    assert stream_datum["seq_nums"] == {"start": 0, "stop": 0}
    assert stream_datum["indices"] == {"start": 0, "stop": 1}


@pytest.mark.parametrize("one_shot_trigger_info", [1, 2, 10, 100], indirect=True)
async def test_can_decribe_collect(
    test_adaravis: adaravis.AravisDetector, one_shot_trigger_info: TriggerInfo
):
    assert (await test_adaravis.describe_collect()) == {}
    await test_adaravis.stage()
    await test_adaravis.prepare(one_shot_trigger_info)
    assert (await test_adaravis.describe_collect()) == {
        "test_adaravis1": {
            "source": "mock+ca://ARAVIS1:HDF1:FullFileName_RBV",
            "shape": [one_shot_trigger_info.exposures_per_event, 10, 10],
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }


async def test_unsupported_trigger_excepts(test_adaravis: adaravis.AravisDetector):
    with patch(
        "ophyd_async.epics.adcore._hdf_writer.ADHDFWriter.open", new_callable=AsyncMock
    ) as mock_open:
        with pytest.raises(
            ValueError,
            # str(EnumClass.value) handling changed in Python 3.11
            match="ADAravis does not support (DetectorTrigger.)?VARIABLE_GATE",
        ):
            await test_adaravis.prepare(
                TriggerInfo(
                    number_of_events=0,
                    trigger=DetectorTrigger.VARIABLE_GATE,
                    deadtime=1,
                    livetime=1,
                    exposure_timeout=3,
                )
            )

    mock_open.assert_called_once()
