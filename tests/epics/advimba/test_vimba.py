import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DetectorTrigger,
    DeviceCollector,
    PathProvider,
    set_mock_value,
)
from ophyd_async.epics.areadetector.vimba import VimbaDetector


@pytest.fixture
async def advimba(
    RE: RunEngine,
    static_path_provider: PathProvider,
) -> VimbaDetector:
    async with DeviceCollector(mock=True):
        advimba = VimbaDetector("VIMBA:", static_path_provider)

    return advimba


async def test_get_deadtime(
    advimba: VimbaDetector,
):
    # Currently Vimba controller doesn't support getting deadtime.
    assert advimba._controller.get_deadtime(0) == 0.001


async def test_arming_trig_modes(advimba: VimbaDetector):
    set_mock_value(advimba.drv.trig_source, "Freerun")
    set_mock_value(advimba.drv.trigger_mode, "Off")
    set_mock_value(advimba.drv.expose_mode, "Timed")

    async def setup_trigger_mode(trig_mode: DetectorTrigger):
        await advimba.controller.arm(num=1, trigger=trig_mode)
        # Prevent timeouts
        set_mock_value(advimba.drv.acquire, True)

    # Default TriggerSource
    assert (await advimba.drv.trig_source.get_value()) == "Freerun"
    assert (await advimba.drv.trigger_mode.get_value()) == "Off"
    assert (await advimba.drv.expose_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.edge_trigger)
    assert (await advimba.drv.trig_source.get_value()) == "Line1"
    assert (await advimba.drv.trigger_mode.get_value()) == "On"
    assert (await advimba.drv.expose_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.constant_gate)
    assert (await advimba.drv.trig_source.get_value()) == "Line1"
    assert (await advimba.drv.trigger_mode.get_value()) == "On"
    assert (await advimba.drv.expose_mode.get_value()) == "TriggerWidth"

    await setup_trigger_mode(DetectorTrigger.internal)
    assert (await advimba.drv.trig_source.get_value()) == "Freerun"
    assert (await advimba.drv.trigger_mode.get_value()) == "Off"
    assert (await advimba.drv.expose_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.variable_gate)
    assert (await advimba.drv.trig_source.get_value()) == "Line1"
    assert (await advimba.drv.trigger_mode.get_value()) == "On"
    assert (await advimba.drv.expose_mode.get_value()) == "TriggerWidth"


async def test_hints_from_hdf_writer(advimba: VimbaDetector):
    assert advimba.hints == {"fields": ["advimba"]}


async def test_can_read(advimba: VimbaDetector):
    # Standard detector can be used as Readable
    assert (await advimba.read()) == {}


async def test_decribe_describes_writer_dataset(advimba: VimbaDetector):
    set_mock_value(advimba._writer.hdf.file_path_exists, True)
    set_mock_value(advimba._writer.hdf.capture, True)

    assert await advimba.describe() == {}
    await advimba.stage()
    assert await advimba.describe() == {
        "advimba": {
            "source": "mock+ca://VIMBA:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }


async def test_can_collect(advimba: VimbaDetector, static_path_provider: PathProvider):
    path_info = static_path_provider()
    full_file_name = path_info.root / path_info.resource_dir / "foo.h5"
    set_mock_value(advimba.hdf.full_file_name, str(full_file_name))
    set_mock_value(advimba._writer.hdf.file_path_exists, True)
    set_mock_value(advimba._writer.hdf.capture, True)
    await advimba.stage()
    docs = [(name, doc) async for name, doc in advimba.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "advimba"
    assert stream_resource["uri"] == "file://localhost" + str(full_file_name)
    assert stream_resource["parameters"] == {
        "dataset": "/entry/data/data",
        "swmr": False,
        "multiplier": 1,
    }
    assert docs[1][0] == "stream_datum"
    stream_datum = docs[1][1]
    assert stream_datum["stream_resource"] == sr_uid
    assert stream_datum["seq_nums"] == {"start": 0, "stop": 0}
    assert stream_datum["indices"] == {"start": 0, "stop": 1}


async def test_can_decribe_collect(advimba: VimbaDetector):
    set_mock_value(advimba._writer.hdf.file_path_exists, True)
    set_mock_value(advimba._writer.hdf.capture, True)
    assert (await advimba.describe_collect()) == {}
    await advimba.stage()
    assert (await advimba.describe_collect()) == {
        "advimba": {
            "source": "mock+ca://VIMBA:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }
