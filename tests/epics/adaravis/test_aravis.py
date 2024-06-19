import re

import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (DetectorTrigger, DeviceCollector,
                              DirectoryProvider, TriggerInfo, set_mock_value)
from ophyd_async.epics import adaravis


@pytest.fixture
async def mock_adaravis(
    RE: RunEngine,
    static_directory_provider: DirectoryProvider,
) -> adaravis.AravisDetector:
    async with DeviceCollector(mock=True):
        mock_adaravis = adaravis.AravisDetector("ADARAVIS:", static_directory_provider)

    return mock_adaravis


@pytest.mark.parametrize("exposure_time", [0.0, 0.1, 1.0, 10.0, 100.0])
async def test_deadtime_invariant_with_exposure_time(
    exposure_time: float,
    mock_adaravis: adaravis.AravisDetector,
):
    assert mock_adaravis.controller.get_deadtime(exposure_time) == 1961e-6


async def test_trigger_source_set_to_gpio_line(mock_adaravis: adaravis.AravisDetector):
    set_mock_value(mock_adaravis.drv.trigger_source, "Freerun")

    async def trigger_and_complete():
        await mock_adaravis.controller.arm(num=1, trigger=DetectorTrigger.edge_trigger)
        # Prevent timeouts
        set_mock_value(mock_adaravis.drv.acquire, True)

    # Default TriggerSource
    assert (await mock_adaravis.drv.trigger_source.get_value()) == "Freerun"
    mock_adaravis.set_external_trigger_gpio(1)
    # TriggerSource not changed by setting gpio
    assert (await mock_adaravis.drv.trigger_source.get_value()) == "Freerun"

    await trigger_and_complete()

    # TriggerSource changes
    assert (await mock_adaravis.drv.trigger_source.get_value()) == "Line1"

    mock_adaravis.set_external_trigger_gpio(3)
    # TriggerSource not changed by setting gpio
    await trigger_and_complete()
    assert (await mock_adaravis.drv.trigger_source.get_value()) == "Line3"


def test_gpio_pin_limited(mock_adaravis: adaravis.AravisDetector):
    assert mock_adaravis.get_external_trigger_gpio() == 1
    mock_adaravis.set_external_trigger_gpio(2)
    assert mock_adaravis.get_external_trigger_gpio() == 2
    with pytest.raises(
        ValueError,
        match=re.escape(
            "AravisDetector only supports the following GPIO indices: "
            "(1, 2, 3, 4) but was asked to use 55"
        ),
    ):
        mock_adaravis.set_external_trigger_gpio(55)  # type: ignore


async def test_hints_from_hdf_writer(mock_adaravis: adaravis.AravisDetector):
    assert mock_adaravis.hints == {"fields": ["adaravis"]}


async def test_can_read(mock_adaravis: adaravis.AravisDetector):
    # Standard detector can be used as Readable
    assert (await mock_adaravis.read()) == {}


async def test_decribe_describes_writer_dataset(mock_adaravis: adaravis.AravisDetector):
    set_mock_value(mock_adaravis._writer.hdf.file_path_exists, True)
    set_mock_value(mock_adaravis._writer.hdf.capture, True)

    assert await mock_adaravis.describe() == {}
    await mock_adaravis.stage()
    assert await mock_adaravis.describe() == {
        "adaravis": {
            "source": "mock+ca://ADARAVIS:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "external": "STREAM:",
        }
    }


async def test_can_collect(
    mock_adaravis: adaravis.AravisDetector, static_directory_provider: DirectoryProvider
):
    directory_info = static_directory_provider()
    full_file_name = directory_info.root / directory_info.resource_dir / "foo.h5"
    set_mock_value(mock_adaravis.hdf.full_file_name, str(full_file_name))
    set_mock_value(mock_adaravis._writer.hdf.file_path_exists, True)
    set_mock_value(mock_adaravis._writer.hdf.capture, True)
    await mock_adaravis.stage()
    docs = [(name, doc) async for name, doc in mock_adaravis.collect_asset_docs(1)]
    assert len(docs) == 2
    assert docs[0][0] == "stream_resource"
    stream_resource = docs[0][1]
    sr_uid = stream_resource["uid"]
    assert stream_resource["data_key"] == "adaravis"
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


async def test_can_decribe_collect(adaramock_adaravisvis: adaravis.AravisDetector):
    set_mock_value(mock_adaravis._writer.hdf.file_path_exists, True)
    set_mock_value(mock_adaravis._writer.hdf.capture, True)
    assert (await mock_adaravis.describe_collect()) == {}
    await mock_adaravis.stage()
    assert (await mock_adaravis.describe_collect()) == {
        "adaravis": {
            "source": "mock+ca://ADARAVIS:HDF1:FullFileName_RBV",
            "shape": (0, 0),
            "dtype": "array",
            "external": "STREAM:",
        }
    }


async def test_unsupported_trigger_excepts(mock_adaravis: adaravis.AravisDetector):
    with pytest.raises(
        ValueError,
        # str(EnumClass.value) handling changed in Python 3.11
        match=r"AravisController only supports the following trigger types: .* but",
    ):
        await mock_adaravis.prepare(TriggerInfo(1, DetectorTrigger.variable_gate, 1, 1))
