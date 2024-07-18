import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DetectorTrigger,
    DeviceCollector,
    StaticPathProvider,
    set_mock_value,
)
from ophyd_async.epics.areadetector.kinetix import KinetixDetector


@pytest.fixture
async def adkinetix(
    RE: RunEngine,
    static_path_provider: StaticPathProvider,
) -> KinetixDetector:
    async with DeviceCollector(mock=True):
        adkinetix = KinetixDetector("KINETIX:", static_path_provider)

    return adkinetix


async def test_get_deadtime(
    adkinetix: KinetixDetector,
):
    # Currently Kinetix driver doesn't support getting deadtime.
    assert adkinetix._controller.get_deadtime(0) == 0.001


async def test_trigger_modes(adkinetix: KinetixDetector):
    set_mock_value(adkinetix.drv.trigger_mode, "Internal")

    async def setup_trigger_mode(trig_mode: DetectorTrigger):
        await adkinetix.controller.arm(num=1, trigger=trig_mode)
        # Prevent timeouts
        set_mock_value(adkinetix.drv.acquire, True)

    # Default TriggerSource
    assert (await adkinetix.drv.trigger_mode.get_value()) == "Internal"

    await setup_trigger_mode(DetectorTrigger.edge_trigger)
    assert (await adkinetix.drv.trigger_mode.get_value()) == "Rising Edge"

    await setup_trigger_mode(DetectorTrigger.constant_gate)
    assert (await adkinetix.drv.trigger_mode.get_value()) == "Exp. Gate"

    await setup_trigger_mode(DetectorTrigger.internal)
    assert (await adkinetix.drv.trigger_mode.get_value()) == "Internal"

    await setup_trigger_mode(DetectorTrigger.variable_gate)
    assert (await adkinetix.drv.trigger_mode.get_value()) == "Exp. Gate"


async def test_hints_from_hdf_writer(adkinetix: KinetixDetector):
    assert adkinetix.hints == {"fields": ["adkinetix"]}


async def test_can_read(adkinetix: KinetixDetector):
    # Standard detector can be used as Readable
    assert (await adkinetix.read()) == {}


async def test_decribe_describes_writer_dataset(adkinetix: KinetixDetector):
    set_mock_value(adkinetix._writer.hdf.file_path_exists, True)
    set_mock_value(adkinetix._writer.hdf.capture, True)

    assert await adkinetix.describe() == {}
    await adkinetix.stage()
    assert await adkinetix.describe() == {
        "adkinetix": {
            "source": "mock+ca://KINETIX:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }


async def test_can_collect(
    adkinetix: KinetixDetector, static_path_provider: StaticPathProvider
):
    path_info = static_path_provider()
    full_file_name = path_info.root / path_info.resource_dir / "foo.h5"
    set_mock_value(adkinetix.hdf.full_file_name, str(full_file_name))
    set_mock_value(adkinetix._writer.hdf.file_path_exists, True)
    set_mock_value(adkinetix._writer.hdf.capture, True)
    await adkinetix.stage()
    docs = [(name, doc) async for name, doc in adkinetix.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "adkinetix"
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


async def test_can_decribe_collect(adkinetix: KinetixDetector):
    set_mock_value(adkinetix._writer.hdf.file_path_exists, True)
    set_mock_value(adkinetix._writer.hdf.capture, True)
    assert (await adkinetix.describe_collect()) == {}
    await adkinetix.stage()
    assert (await adkinetix.describe_collect()) == {
        "adkinetix": {
            "source": "mock+ca://KINETIX:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }
