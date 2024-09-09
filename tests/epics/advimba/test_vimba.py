import pytest

from ophyd_async.core import (
    DetectorTrigger,
    PathProvider,
    set_mock_value,
)
from ophyd_async.core._detector import TriggerInfo
from ophyd_async.epics import advimba


@pytest.fixture
async def test_advimba(ad_standard_det_factory) -> advimba.VimbaDetector:
    test_advimba = await ad_standard_det_factory(advimba.VimbaDetector)

    return test_advimba


async def test_get_deadtime(
    test_advimba: advimba.VimbaDetector,
):
    # Currently Vimba controller doesn't support getting deadtime.
    assert test_advimba._controller.get_deadtime(0) == 0.001


async def test_arming_trig_modes(test_advimba: advimba.VimbaDetector):
    set_mock_value(test_advimba.drv.trigger_source, "Freerun")
    set_mock_value(test_advimba.drv.trigger_mode, "Off")
    set_mock_value(test_advimba.drv.exposure_mode, "Timed")

    async def setup_trigger_mode(trig_mode: DetectorTrigger):
        await test_advimba.controller.arm(num=1, trigger=trig_mode)
        # Prevent timeouts
        set_mock_value(test_advimba.drv.acquire, True)

    # Default TriggerSource
    assert (await test_advimba.drv.trigger_source.get_value()) == "Freerun"
    assert (await test_advimba.drv.trigger_mode.get_value()) == "Off"
    assert (await test_advimba.drv.exposure_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.edge_trigger)
    assert (await test_advimba.drv.trigger_source.get_value()) == "Line1"
    assert (await test_advimba.drv.trigger_mode.get_value()) == "On"
    assert (await test_advimba.drv.exposure_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.constant_gate)
    assert (await test_advimba.drv.trigger_source.get_value()) == "Line1"
    assert (await test_advimba.drv.trigger_mode.get_value()) == "On"
    assert (await test_advimba.drv.exposure_mode.get_value()) == "TriggerWidth"

    await setup_trigger_mode(DetectorTrigger.internal)
    assert (await test_advimba.drv.trigger_source.get_value()) == "Freerun"
    assert (await test_advimba.drv.trigger_mode.get_value()) == "Off"
    assert (await test_advimba.drv.exposure_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.variable_gate)
    assert (await test_advimba.drv.trigger_source.get_value()) == "Line1"
    assert (await test_advimba.drv.trigger_mode.get_value()) == "On"
    assert (await test_advimba.drv.exposure_mode.get_value()) == "TriggerWidth"


async def test_hints_from_hdf_writer(test_advimba: advimba.VimbaDetector):
    assert test_advimba.hints == {"fields": ["test_advimba1"]}


async def test_can_read(test_advimba: advimba.VimbaDetector):
    # Standard detector can be used as Readable
    assert (await test_advimba.read()) == {}


async def test_decribe_describes_writer_dataset(
    test_advimba: advimba.VimbaDetector, one_shot_trigger_info: TriggerInfo
):
    set_mock_value(test_advimba._writer.hdf.file_path_exists, True)
    set_mock_value(test_advimba._writer.hdf.capture, True)

    assert await test_advimba.describe() == {}
    await test_advimba.stage()
    await test_advimba.prepare(one_shot_trigger_info)
    assert await test_advimba.describe() == {
        "test_advimba1": {
            "source": "mock+ca://VIMBA1:HDF1:FullFileName_RBV",
            "shape": (10, 10),
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }


async def test_can_collect(
    test_advimba: advimba.VimbaDetector,
    static_path_provider: PathProvider,
    one_shot_trigger_info: TriggerInfo,
):
    path_info = static_path_provider()
    full_file_name = path_info.directory_path / "foo.h5"
    set_mock_value(test_advimba.hdf.full_file_name, str(full_file_name))
    set_mock_value(test_advimba._writer.hdf.file_path_exists, True)
    set_mock_value(test_advimba._writer.hdf.capture, True)
    await test_advimba.stage()
    await test_advimba.prepare(one_shot_trigger_info)
    docs = [(name, doc) async for name, doc in test_advimba.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "test_advimba1"
    assert stream_resource["uri"] == "file://localhost" + str(full_file_name)
    assert stream_resource["parameters"] == {
        "dataset": "/entry/data/data",
        "swmr": False,
        "multiplier": 1,
        "chunk_size": (1, 10, 10),
    }
    assert docs[1][0] == "stream_datum"
    stream_datum = docs[1][1]
    assert stream_datum["stream_resource"] == sr_uid
    assert stream_datum["seq_nums"] == {"start": 0, "stop": 0}
    assert stream_datum["indices"] == {"start": 0, "stop": 1}


async def test_can_decribe_collect(
    test_advimba: advimba.VimbaDetector, one_shot_trigger_info: TriggerInfo
):
    set_mock_value(test_advimba._writer.hdf.file_path_exists, True)
    set_mock_value(test_advimba._writer.hdf.capture, True)
    assert (await test_advimba.describe_collect()) == {}
    await test_advimba.stage()
    await test_advimba.prepare(one_shot_trigger_info)
    assert (await test_advimba.describe_collect()) == {
        "test_advimba1": {
            "source": "mock+ca://VIMBA1:HDF1:FullFileName_RBV",
            "shape": (10, 10),
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }
