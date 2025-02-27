from typing import cast

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    PathProvider,
    TriggerInfo,
)
from ophyd_async.epics import adcore, advimba
from ophyd_async.epics.advimba import (
    VimbaExposeOutMode,
    VimbaOnOff,
    VimbaTriggerSource,
)
from ophyd_async.testing import set_mock_value


@pytest.fixture
def test_advimba(ad_standard_det_factory) -> advimba.VimbaDetector:
    return ad_standard_det_factory(advimba.VimbaDetector, adcore.ADHDFWriter)


async def test_get_deadtime(
    test_advimba: advimba.VimbaDetector,
):
    # Currently Vimba controller doesn't support getting deadtime.
    assert test_advimba._controller.get_deadtime(0) == 0.001


async def test_arming_trig_modes(test_advimba: advimba.VimbaDetector):
    driver = cast(advimba.VimbaDriverIO, test_advimba.driver)

    set_mock_value(driver.trigger_source, VimbaTriggerSource.FREERUN)
    set_mock_value(driver.trigger_mode, VimbaOnOff.OFF)
    set_mock_value(driver.exposure_mode, VimbaExposeOutMode.TIMED)

    async def setup_trigger_mode(trig_mode: DetectorTrigger):
        await test_advimba._controller.prepare(
            TriggerInfo(number_of_events=1, trigger=trig_mode)
        )
        await test_advimba._controller.arm()
        await test_advimba._controller.wait_for_idle()
        # Prevent timeouts
        set_mock_value(driver.acquire, True)

    # Default TriggerSource
    assert (await driver.trigger_source.get_value()) == "Freerun"
    assert (await driver.trigger_mode.get_value()) == "Off"
    assert (await driver.exposure_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.EDGE_TRIGGER)
    assert (await driver.trigger_source.get_value()) == "Line1"
    assert (await driver.trigger_mode.get_value()) == "On"
    assert (await driver.exposure_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.CONSTANT_GATE)
    assert (await driver.trigger_source.get_value()) == "Line1"
    assert (await driver.trigger_mode.get_value()) == "On"
    assert (await driver.exposure_mode.get_value()) == "TriggerWidth"

    await setup_trigger_mode(DetectorTrigger.INTERNAL)
    assert (await driver.trigger_source.get_value()) == "Freerun"
    assert (await driver.trigger_mode.get_value()) == "Off"
    assert (await driver.exposure_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.VARIABLE_GATE)
    assert (await driver.trigger_source.get_value()) == "Line1"
    assert (await driver.trigger_mode.get_value()) == "On"
    assert (await driver.exposure_mode.get_value()) == "TriggerWidth"


async def test_hints_from_hdf_writer(test_advimba: advimba.VimbaDetector):
    assert test_advimba.hints == {"fields": [test_advimba.name]}


async def test_can_read(test_advimba: advimba.VimbaDetector):
    # Standard detector can be used as Readable
    assert (await test_advimba.read()) == {}


async def test_decribe_describes_writer_dataset(
    test_advimba: advimba.VimbaDetector, one_shot_trigger_info: TriggerInfo
):
    assert await test_advimba.describe() == {}
    await test_advimba.stage()
    await test_advimba.prepare(one_shot_trigger_info)
    assert await test_advimba.describe() == {
        "test_advimba1": {
            "source": "mock+ca://VIMBA1:HDF1:FullFileName_RBV",
            "shape": [1, 10, 10],
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }


@pytest.mark.parametrize("one_shot_trigger_info", [1, 2, 10, 100], indirect=True)
async def test_can_collect(
    test_advimba: advimba.VimbaDetector,
    static_path_provider: PathProvider,
    one_shot_trigger_info: TriggerInfo,
):
    path_info = static_path_provider()
    full_file_name = path_info.directory_path / f"{path_info.filename}.h5"

    await test_advimba.stage()
    await test_advimba.prepare(one_shot_trigger_info)
    docs = [(name, doc) async for name, doc in test_advimba.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "test_advimba1"
    assert stream_resource["uri"] == "file://localhost/" + str(full_file_name).lstrip(
        "/"
    )
    assert stream_resource["parameters"] == {
        "dataset": "/entry/data/data",
        "chunk_shape": (1, 10, 10),
    }
    assert docs[1][0] == "stream_datum"
    stream_datum = docs[1][1]
    assert stream_datum["stream_resource"] == sr_uid
    assert stream_datum["seq_nums"] == {"start": 0, "stop": 0}
    assert stream_datum["indices"] == {"start": 0, "stop": 1}


@pytest.mark.parametrize("one_shot_trigger_info", [1, 2, 10, 100], indirect=True)
async def test_can_decribe_collect(
    test_advimba: advimba.VimbaDetector, one_shot_trigger_info: TriggerInfo
):
    assert (await test_advimba.describe_collect()) == {}
    await test_advimba.stage()
    await test_advimba.prepare(one_shot_trigger_info)
    assert (await test_advimba.describe_collect()) == {
        "test_advimba1": {
            "source": "mock+ca://VIMBA1:HDF1:FullFileName_RBV",
            "shape": [one_shot_trigger_info.exposures_per_event, 10, 10],
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }
