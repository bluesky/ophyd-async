import pytest

from ophyd_async.core import (
    StaticPathProvider,
    TriggerInfo,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore, adsimdetector


@pytest.fixture
async def hdf_det(
    static_path_provider: StaticPathProvider,
):
    async with init_devices(mock=True):
        detector = adsimdetector.sim_detector(
            "PREFIX:",
            static_path_provider,
            plugins={"stats": adcore.NDStatsIO("PREFIX:STATS:")},
        )
    set_mock_value(detector.driver.array_size_x, 1024)
    set_mock_value(detector.driver.array_size_y, 768)
    set_mock_value(detector.driver.data_type, adcore.ADBaseDataType.UINT16)
    return detector


async def test_hdf_describe_just_data(hdf_det: adcore.AreaDetector[adcore.ADBaseIO]):
    writer = hdf_det.get_plugin("writer", adcore.NDFilePluginIO)
    set_mock_value(writer.file_path_exists, True)
    await hdf_det.prepare(TriggerInfo(number_of_events=3))
    desc = await hdf_det.describe()
    directory = await writer.file_path.get_value()
    assert directory[0] == directory[-1] == "/"
    assert desc == {
        "detector": {
            "dtype": "array",
            "dtype_numpy": "<u2",
            "external": "STREAM:",
            "shape": [
                1,
                768,
                1024,
            ],
            "source": f"file://localhost{directory}ophyd_async_tests.h5",
        },
    }
