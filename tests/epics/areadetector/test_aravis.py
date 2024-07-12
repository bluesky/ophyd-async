import re

import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DetectorTrigger,
    DeviceCollector,
    DirectoryProvider,
    TriggerInfo,
    set_mock_value,
)
from ophyd_async.epics.areadetector.aravis import AravisDetector


@pytest.fixture
async def adaravis(
    RE: RunEngine,
    static_directory_provider: DirectoryProvider,
) -> AravisDetector:
    async with DeviceCollector(mock=True):
        adaravis = AravisDetector("ADARAVIS:", static_directory_provider)

    return adaravis


@pytest.mark.parametrize("exposure_time", [0.0, 0.1, 1.0, 10.0, 100.0])
async def test_deadtime_invariant_with_exposure_time(
    exposure_time: float,
    adaravis: AravisDetector,
):
    assert adaravis.controller.get_deadtime(exposure_time) == 1961e-6


async def test_trigger_source_set_to_gpio_line(adaravis: AravisDetector):
    set_mock_value(adaravis.drv.trigger_source, "Freerun")

    async def trigger_and_complete():
        await adaravis.controller.arm(num=1, trigger=DetectorTrigger.edge_trigger)
        # Prevent timeouts
        set_mock_value(adaravis.drv.acquire, True)

    # Default TriggerSource
    assert (await adaravis.drv.trigger_source.get_value()) == "Freerun"
    adaravis.set_external_trigger_gpio(1)
    # TriggerSource not changed by setting gpio
    assert (await adaravis.drv.trigger_source.get_value()) == "Freerun"

    await trigger_and_complete()

    # TriggerSource changes
    assert (await adaravis.drv.trigger_source.get_value()) == "Line1"

    adaravis.set_external_trigger_gpio(3)
    # TriggerSource not changed by setting gpio
    await trigger_and_complete()
    assert (await adaravis.drv.trigger_source.get_value()) == "Line3"


def test_gpio_pin_limited(adaravis: AravisDetector):
    assert adaravis.get_external_trigger_gpio() == 1
    adaravis.set_external_trigger_gpio(2)
    assert adaravis.get_external_trigger_gpio() == 2
    with pytest.raises(
        ValueError,
        match=re.escape(
            "AravisDetector only supports the following GPIO indices: "
            "(1, 2, 3, 4) but was asked to use 55"
        ),
    ):
        adaravis.set_external_trigger_gpio(55)  # type: ignore


async def test_hints_from_hdf_writer(adaravis: AravisDetector):
    assert adaravis.hints == {"fields": ["adaravis"]}


async def test_can_read(adaravis: AravisDetector):
    # Standard detector can be used as Readable
    assert (await adaravis.read()) == {}


async def test_decribe_describes_writer_dataset(adaravis: AravisDetector):
    set_mock_value(adaravis._writer.hdf.file_path_exists, True)
    set_mock_value(adaravis._writer.hdf.capture, True)

    assert await adaravis.describe() == {}
    await adaravis.stage()
    assert await adaravis.describe() == {
        "adaravis": {
            "source": "mock+ca://ADARAVIS:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }


async def test_can_collect(
    adaravis: AravisDetector, static_directory_provider: DirectoryProvider
):
    directory_info = static_directory_provider()
    full_file_name = "foo.h5"
    set_mock_value(adaravis.hdf.full_file_name, str(full_file_name))
    set_mock_value(adaravis._writer.hdf.file_path_exists, True)
    set_mock_value(adaravis._writer.hdf.capture, True)
    await adaravis.stage()
    docs = [(name, doc) async for name, doc in adaravis.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "adaravis"

    assert (
        stream_resource["uri"]
        == "file://localhost" + str(directory_info.root) + "/foo.h5"
    )
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


async def test_can_decribe_collect(adaravis: AravisDetector):
    set_mock_value(adaravis._writer.hdf.file_path_exists, True)
    set_mock_value(adaravis._writer.hdf.capture, True)
    assert (await adaravis.describe_collect()) == {}
    await adaravis.stage()
    assert (await adaravis.describe_collect()) == {
        "adaravis": {
            "source": "mock+ca://ADARAVIS:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "dtype_numpy": "|i1",
            "external": "STREAM:",
        }
    }


async def test_unsupported_trigger_excepts(adaravis: AravisDetector):
    with pytest.raises(
        ValueError,
        # str(EnumClass.value) handling changed in Python 3.11
        match=r"AravisController only supports the following trigger types: .* but",
    ):
        await adaravis.prepare(
            TriggerInfo(
                number=1,
                trigger=DetectorTrigger.variable_gate,
                deadtime=1,
                livetime=1,
                frame_timeout=3,
            )
        )
