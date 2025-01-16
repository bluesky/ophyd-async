from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from event_model import StreamDatum, StreamResource

from ophyd_async.core import (
    DetectorTrigger,
    PathProvider,
    TriggerInfo,
)
from ophyd_async.epics import adandor


@pytest.fixture
def test_adandor(ad_standard_det_factory) -> adandor.Andor2Detector:
    return ad_standard_det_factory(adandor.Andor2Detector)


@pytest.mark.parametrize("exposure_time", [0.0, 0.1, 1.0, 10.0, 100.0])
async def test_deadtime_from_exposure_time(
    exposure_time: float,
    test_adandor: adandor.Andor2Detector,
):
    assert test_adandor._controller.get_deadtime(exposure_time) == exposure_time + 0.1


async def test_hints_from_hdf_writer(test_adandor: adandor.Andor2Detector):
    assert test_adandor.hints == {"fields": ["test_adandor21"]}


async def test_can_read(test_adandor: adandor.Andor2Detector):
    # Standard detector can be used as Readable
    assert (await test_adandor.read()) == {}


async def test_decribe_describes_writer_dataset(
    test_adandor: adandor.Andor2Detector, one_shot_trigger_info: TriggerInfo
):
    assert await test_adandor.describe() == {}
    await test_adandor.stage()
    await test_adandor.prepare(one_shot_trigger_info)
    assert await test_adandor.describe() == {
        "test_adandor21": {
            "source": "mock+ca://ANDOR21:HDF1:FullFileName_RBV",
            "shape": [10, 10],
            "dtype": "array",
            "dtype_numpy": "<u2",
            "external": "STREAM:",
        }
    }


async def test_can_collect(
    test_adandor: adandor.Andor2Detector,
    static_path_provider: PathProvider,
    one_shot_trigger_info: TriggerInfo,
):
    path_info = static_path_provider()
    full_file_name = path_info.directory_path / f"{path_info.filename}.h5"
    await test_adandor.stage()
    await test_adandor.prepare(one_shot_trigger_info)
    docs = [(name, doc) async for name, doc in test_adandor.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = cast(StreamResource, docs[0][1])
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "test_adandor21"
    assert stream_resource["uri"] == "file://localhost/" + str(full_file_name).lstrip(
        "/"
    )
    assert stream_resource["parameters"] == {
        "dataset": "/entry/data/data",
        "swmr": False,
        "multiplier": 1,
        "chunk_shape": (1, 10, 10),
    }
    assert docs[1][0] == "stream_datum"
    stream_datum = cast(StreamDatum, docs[1][1])
    assert stream_datum["stream_resource"] == sr_uid
    assert stream_datum["seq_nums"] == {"start": 0, "stop": 0}
    assert stream_datum["indices"] == {"start": 0, "stop": 1}


async def test_can_decribe_collect(
    test_adandor: adandor.Andor2Detector, one_shot_trigger_info: TriggerInfo
):
    assert (await test_adandor.describe_collect()) == {}
    await test_adandor.stage()
    await test_adandor.prepare(one_shot_trigger_info)
    assert (await test_adandor.describe_collect()) == {
        "test_adandor21": {
            "source": "mock+ca://ANDOR21:HDF1:FullFileName_RBV",
            "shape": [10, 10],
            "dtype": "array",
            "dtype_numpy": "<u2",
            "external": "STREAM:",
        }
    }


async def test_unsupported_trigger_excepts(test_adandor: adandor.Andor2Detector):
    with patch(
        "ophyd_async.epics.adcore._hdf_writer.ADHDFWriter.open", new_callable=AsyncMock
    ) as mock_open:
        with pytest.raises(
            ValueError,
            # str(EnumClass.value) handling changed in Python 3.11
            match=(
                "Andor2Controller only supports the following trigger types: .* but"
            ),
        ):
            await test_adandor.prepare(
                TriggerInfo(
                    number_of_triggers=0,
                    trigger=DetectorTrigger.VARIABLE_GATE,
                    deadtime=1.1,
                    livetime=1,
                    frame_timeout=3,
                )
            )

    mock_open.assert_called_once()
