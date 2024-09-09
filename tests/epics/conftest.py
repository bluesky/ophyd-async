import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core._detector import StandardDetector
from ophyd_async.core._device import DeviceCollector
from ophyd_async.core._mock_signal_utils import set_mock_value


@pytest.fixture
async def ad_standard_det_factory(
    RE: RunEngine,
    static_path_provider,
) -> StandardDetector:
    async def generate_ad_standard_det(ad_standard_detector_class, number=1):
        detector_name = ad_standard_detector_class.__name__
        if detector_name.endswith("Detector"):
            detector_name = detector_name[:-8]

        async with DeviceCollector(mock=True):
            test_adstandard_det = ad_standard_detector_class(
                f"{detector_name.upper()}{number}:",
                static_path_provider,
                name=f"test_ad{detector_name.lower()}{number}",
            )

        # Set number of frames per chunk and frame dimensions to something reasonable
        set_mock_value(test_adstandard_det.hdf.num_frames_chunks, 1)
        set_mock_value(test_adstandard_det.drv.array_size_x, 10)
        set_mock_value(test_adstandard_det.drv.array_size_y, 10)

        return test_adstandard_det

    return generate_ad_standard_det
