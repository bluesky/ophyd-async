import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DetectorTrigger,
    DeviceCollector,
    DirectoryProvider,
    set_mock_value,
)
from ophyd_async.epics import adkinetix


@pytest.fixture
async def mock_adkinetix(
    RE: RunEngine,
    static_directory_provider: DirectoryProvider,
) -> adkinetix.KinetixDetector:
    async with DeviceCollector(mock=True):
        mock_adkinetix = adkinetix.KinetixDetector("KINETIX:", static_directory_provider)

    return mock_adkinetix


async def test_get_deadtime(
    mock_adkinetix: adkinetix.KinetixDetector,
):
    # Currently Kinetix driver doesn't support getting deadtime.
    assert mock_adkinetix._controller.get_deadtime(0) == 0.001


async def test_trigger_modes(mock_adkinetix: adkinetix.KinetixDetector):
    set_mock_value(mock_adkinetix.drv.trigger_mode, "Internal")

    async def setup_trigger_mode(trig_mode: DetectorTrigger):
        await mock_adkinetix.controller.arm(num=1, trigger=trig_mode)
        # Prevent timeouts
        set_mock_value(mock_adkinetix.drv.acquire, True)

    # Default TriggerSource
    assert (await mock_adkinetix.drv.trigger_mode.get_value()) == "Internal"

    await setup_trigger_mode(DetectorTrigger.edge_trigger)
    assert (await mock_adkinetix.drv.trigger_mode.get_value()) == "Rising Edge"

    await setup_trigger_mode(DetectorTrigger.constant_gate)
    assert (await mock_adkinetix.drv.trigger_mode.get_value()) == "Exp. Gate"

    await setup_trigger_mode(DetectorTrigger.internal)
    assert (await mock_adkinetix.drv.trigger_mode.get_value()) == "Internal"

    await setup_trigger_mode(DetectorTrigger.variable_gate)
    assert (await mock_adkinetix.drv.trigger_mode.get_value()) == "Exp. Gate"


async def test_hints_from_hdf_writer(mock_adkinetix: adkinetix.KinetixDetector):
    assert mock_adkinetix.hints == {"fields": ["adkinetix"]}


async def test_can_read(mock_adkinetix: adkinetix.KinetixDetector):
    # Standard detector can be used as Readable
    assert (await mock_adkinetix.read()) == {}


async def test_decribe_describes_writer_dataset(mock_adkinetix: adkinetix.KinetixDetector):
    set_mock_value(mock_adkinetix._writer.hdf.file_path_exists, True)
    set_mock_value(mock_adkinetix._writer.hdf.capture, True)

    assert await mock_adkinetix.describe() == {}
    await mock_adkinetix.stage()
    assert await mock_adkinetix.describe() == {
        "adkinetix": {
            "source": "mock+ca://KINETIX:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "external": "STREAM:",
        }
    }


async def test_can_collect(
    mock_adkinetix: adkinetix.KinetixDetector, static_directory_provider: DirectoryProvider
):
    directory_info = static_directory_provider()
    full_file_name = directory_info.root / directory_info.resource_dir / "foo.h5"
    set_mock_value(mock_adkinetix.hdf.full_file_name, str(full_file_name))
    set_mock_value(mock_adkinetix._writer.hdf.file_path_exists, True)
    set_mock_value(mock_adkinetix._writer.hdf.capture, True)
    await mock_adkinetix.stage()
    docs = [(name, doc) async for name, doc in mock_adkinetix.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "adkinetix"
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


async def test_can_decribe_collect(mock_adkinetix: adkinetix.KinetixDetector):
    set_mock_value(mock_adkinetix._writer.hdf.file_path_exists, True)
    set_mock_value(mock_adkinetix._writer.hdf.capture, True)
    assert (await mock_adkinetix.describe_collect()) == {}
    await mock_adkinetix.stage()
    assert (await mock_adkinetix.describe_collect()) == {
        "adkinetix": {
            "source": "mock+ca://KINETIX:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "external": "STREAM:",
        }
    }
