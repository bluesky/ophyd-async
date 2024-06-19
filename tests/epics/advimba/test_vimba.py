import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DetectorTrigger,
    DeviceCollector,
    DirectoryProvider,
    set_mock_value,
)
from ophyd_async.epics import advimba


@pytest.fixture
async def mock_advimba(
    RE: RunEngine,
    static_directory_provider: DirectoryProvider,
) -> advimba.VimbaDetector:
    async with DeviceCollector(mock=True):
        mock_advimba = advimba.VimbaDetector("VIMBA:", static_directory_provider)

    return mock_advimba


async def test_get_deadtime(
    mock_advimba: advimba.VimbaDetector,
):
    # Currently Vimba controller doesn't support getting deadtime.
    assert mock_advimba._controller.get_deadtime(0) == 0.001


async def test_arming_trig_modes(mock_advimba: advimba.VimbaDetector):
    set_mock_value(mock_advimba.drv.trig_source, "Freerun")
    set_mock_value(mock_advimba.drv.trigger_mode, "Off")
    set_mock_value(mock_advimba.drv.expose_mode, "Timed")

    async def setup_trigger_mode(trig_mode: DetectorTrigger):
        await mock_advimba.controller.arm(num=1, trigger=trig_mode)
        # Prevent timeouts
        set_mock_value(mock_advimba.drv.acquire, True)

    # Default TriggerSource
    assert (await mock_advimba.drv.trig_source.get_value()) == "Freerun"
    assert (await mock_advimba.drv.trigger_mode.get_value()) == "Off"
    assert (await mock_advimba.drv.expose_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.edge_trigger)
    assert (await mock_advimba.drv.trig_source.get_value()) == "Line1"
    assert (await mock_advimba.drv.trigger_mode.get_value()) == "On"
    assert (await mock_advimba.drv.expose_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.constant_gate)
    assert (await mock_advimba.drv.trig_source.get_value()) == "Line1"
    assert (await mock_advimba.drv.trigger_mode.get_value()) == "On"
    assert (await mock_advimba.drv.expose_mode.get_value()) == "TriggerWidth"

    await setup_trigger_mode(DetectorTrigger.internal)
    assert (await mock_advimba.drv.trig_source.get_value()) == "Freerun"
    assert (await mock_advimba.drv.trigger_mode.get_value()) == "Off"
    assert (await mock_advimba.drv.expose_mode.get_value()) == "Timed"

    await setup_trigger_mode(DetectorTrigger.variable_gate)
    assert (await mock_advimba.drv.trig_source.get_value()) == "Line1"
    assert (await mock_advimba.drv.trigger_mode.get_value()) == "On"
    assert (await mock_advimba.drv.expose_mode.get_value()) == "TriggerWidth"


async def test_hints_from_hdf_writer(mock_advimba: advimba.VimbaDetector):
    assert mock_advimba.hints == {"fields": ["advimba"]}


async def test_can_read(mock_advimba: advimba.VimbaDetector):
    # Standard detector can be used as Readable
    assert (await mock_advimba.read()) == {}


async def test_decribe_describes_writer_dataset(mock_advimba: advimba.VimbaDetector):
    set_mock_value(mock_advimba._writer.hdf.file_path_exists, True)
    set_mock_value(mock_advimba._writer.hdf.capture, True)

    assert await mock_advimba.describe() == {}
    await mock_advimba.stage()
    assert await mock_advimba.describe() == {
        "advimba": {
            "source": "mock+ca://VIMBA:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "external": "STREAM:",
        }
    }


async def test_can_collect(
    mock_advimba: advimba.VimbaDetector, static_directory_provider: DirectoryProvider
):
    directory_info = static_directory_provider()
    full_file_name = directory_info.root / directory_info.resource_dir / "foo.h5"
    set_mock_value(mock_advimba.hdf.full_file_name, str(full_file_name))
    set_mock_value(mock_advimba._writer.hdf.file_path_exists, True)
    set_mock_value(mock_advimba._writer.hdf.capture, True)
    await mock_advimba.stage()
    docs = [(name, doc) async for name, doc in mock_advimba.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "advimba"
    assert stream_resource["spec"] == "AD_HDF5_SWMR_SLICE"
    assert stream_resource["root"] == str(directory_info.root)
    assert stream_resource["resource_path"] == str(
        directory_info.resource_dir / "foo.h5"
    )
    assert stream_resource["path_semantics"] == "posix"
    assert stream_resource["resource_kwargs"] == {
        "path": "/entry/data/data",
        "multiplier": 1,
        "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
    }
    assert docs[1][0] == "stream_datum"
    stream_datum = docs[1][1]
    assert stream_datum["stream_resource"] == sr_uid
    assert stream_datum["seq_nums"] == {"start": 0, "stop": 0}
    assert stream_datum["indices"] == {"start": 0, "stop": 1}


async def test_can_decribe_collect(mock_advimba: advimba.VimbaDetector):
    set_mock_value(mock_advimba._writer.hdf.file_path_exists, True)
    set_mock_value(mock_advimba._writer.hdf.capture, True)
    assert (await mock_advimba.describe_collect()) == {}
    await mock_advimba.stage()
    assert (await mock_advimba.describe_collect()) == {
        "advimba": {
            "source": "mock+ca://VIMBA:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "external": "STREAM:",
        }
    }
