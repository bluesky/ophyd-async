import pytest

from ophyd_async.core import (
    DetectorTrigger,
    StaticPathProvider,
    set_mock_value,
)
from ophyd_async.core._detector import TriggerInfo
from ophyd_async.epics import adkinetix
from ophyd_async.epics.adkinetix._kinetix_io import KinetixTriggerMode


@pytest.fixture
def test_adkinetix(ad_standard_det_factory):
    return ad_standard_det_factory(adkinetix.KinetixDetector)


async def test_get_deadtime(
    test_adkinetix: adkinetix.KinetixDetector,
):
    # Currently Kinetix driver doesn't support getting deadtime.
    assert test_adkinetix._controller.get_deadtime(0) == 0.001


async def test_trigger_modes(test_adkinetix: adkinetix.KinetixDetector):
    set_mock_value(test_adkinetix.drv.trigger_mode, KinetixTriggerMode.internal)

    async def setup_trigger_mode(trig_mode: DetectorTrigger):
        await test_adkinetix.controller.prepare(
            TriggerInfo(number_of_triggers=1, trigger=trig_mode)
        )
        await test_adkinetix.controller.arm()
        await test_adkinetix.controller.wait_for_idle()
        # Prevent timeouts
        set_mock_value(test_adkinetix.drv.acquire, True)

    # Default TriggerSource
    assert (await test_adkinetix.drv.trigger_mode.get_value()) == "Internal"

    await setup_trigger_mode(DetectorTrigger.edge_trigger)
    assert (await test_adkinetix.drv.trigger_mode.get_value()) == "Rising Edge"

    await setup_trigger_mode(DetectorTrigger.constant_gate)
    assert (await test_adkinetix.drv.trigger_mode.get_value()) == "Exp. Gate"

    await setup_trigger_mode(DetectorTrigger.internal)
    assert (await test_adkinetix.drv.trigger_mode.get_value()) == "Internal"

    await setup_trigger_mode(DetectorTrigger.variable_gate)
    assert (await test_adkinetix.drv.trigger_mode.get_value()) == "Exp. Gate"


async def test_hints_from_hdf_writer(test_adkinetix: adkinetix.KinetixDetector):
    assert test_adkinetix.hints == {"fields": [test_adkinetix.name]}


async def test_can_read(test_adkinetix: adkinetix.KinetixDetector):
    # Standard detector can be used as Readable
    assert (await test_adkinetix.read()) == {}


async def test_decribe_describes_writer_dataset(
    test_adkinetix: adkinetix.KinetixDetector, one_shot_trigger_info: TriggerInfo
):
    assert await test_adkinetix.describe() == {}
    await test_adkinetix.stage()
    await test_adkinetix.prepare(one_shot_trigger_info)
    assert await test_adkinetix.describe() == {
        "test_adkinetix1": {
            "source": "mock+ca://KINETIX1:HDF1:FullFileName_RBV",
            "shape": (10, 10),
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }


async def test_can_collect(
    test_adkinetix: adkinetix.KinetixDetector,
    static_path_provider: StaticPathProvider,
    one_shot_trigger_info: TriggerInfo,
):
    path_info = static_path_provider()
    full_file_name = path_info.directory_path / f"{path_info.filename}.h5"

    await test_adkinetix.stage()
    await test_adkinetix.prepare(one_shot_trigger_info)
    docs = [(name, doc) async for name, doc in test_adkinetix.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "test_adkinetix1"
    assert stream_resource["uri"] == "file://localhost" + str(full_file_name)
    assert stream_resource["parameters"] == {
        "dataset": "/entry/data/data",
        "swmr": False,
        "multiplier": 1,
        "chunk_shape": (1, 10, 10),
    }
    assert docs[1][0] == "stream_datum"
    stream_datum = docs[1][1]
    assert stream_datum["stream_resource"] == sr_uid
    assert stream_datum["seq_nums"] == {"start": 0, "stop": 0}
    assert stream_datum["indices"] == {"start": 0, "stop": 1}


async def test_can_decribe_collect(
    test_adkinetix: adkinetix.KinetixDetector, one_shot_trigger_info: TriggerInfo
):
    assert (await test_adkinetix.describe_collect()) == {}
    await test_adkinetix.stage()
    await test_adkinetix.prepare(one_shot_trigger_info)
    assert (await test_adkinetix.describe_collect()) == {
        "test_adkinetix1": {
            "source": "mock+ca://KINETIX1:HDF1:FullFileName_RBV",
            "shape": (10, 10),
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }
