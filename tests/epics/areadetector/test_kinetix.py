import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DetectorTrigger,
    DeviceCollector,
    DirectoryProvider,
    set_sim_value,
)
from ophyd_async.epics.areadetector.kinetix import KinetixDetector


@pytest.fixture
async def adkinetix(
    RE: RunEngine,
    static_directory_provider: DirectoryProvider,
) -> KinetixDetector:
    async with DeviceCollector(sim=True):
        adkinetix = KinetixDetector("KINETIX:", static_directory_provider)

    return adkinetix


async def test_get_deadtime(
    adkinetix: KinetixDetector,
):
    # Currently Kinetix driver doesn't support getting deadtime.
    assert adkinetix._controller.get_deadtime(0) == 0.001


async def test_trigger_modes(adkinetix: KinetixDetector):
    set_sim_value(adkinetix.drv.trigger_mode, "Internal")

    async def setup_trigger_mode(trig_mode: DetectorTrigger):
        await adkinetix.controller.arm(num=1, trigger=trig_mode)
        # Prevent timeouts
        set_sim_value(adkinetix.drv.acquire, True)

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
    set_sim_value(adkinetix._writer.hdf.file_path_exists, True)
    set_sim_value(adkinetix._writer.hdf.capture, True)

    assert await adkinetix.describe() == {}
    await adkinetix.stage()
    assert await adkinetix.describe() == {
        "adkinetix": {
            "source": "soft://adkinetix-hdf-full_file_name",
            "shape": (0, 0),
            "dtype": "array",
            "external": "STREAM:",
        }
    }


async def test_can_collect(
    adkinetix: KinetixDetector, static_directory_provider: DirectoryProvider
):
    directory_info = static_directory_provider()
    full_file_name = directory_info.root / directory_info.resource_dir / "foo.h5"
    set_sim_value(adkinetix.hdf.full_file_name, str(full_file_name))
    set_sim_value(adkinetix._writer.hdf.file_path_exists, True)
    set_sim_value(adkinetix._writer.hdf.capture, True)
    await adkinetix.stage()
    docs = [(name, doc) async for name, doc in adkinetix.collect_asset_docs(1)]
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


async def test_can_decribe_collect(adkinetix: KinetixDetector):
    set_sim_value(adkinetix._writer.hdf.file_path_exists, True)
    set_sim_value(adkinetix._writer.hdf.capture, True)
    assert (await adkinetix.describe_collect()) == {}
    await adkinetix.stage()
    assert (await adkinetix.describe_collect()) == {
        "adkinetix": {
            "source": "soft://adkinetix-hdf-full_file_name",
            "shape": (0, 0),
            "dtype": "array",
            "external": "STREAM:",
        }
    }
