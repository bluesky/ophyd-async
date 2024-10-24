import os
from collections.abc import Callable

import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core._detector import StandardDetector
from ophyd_async.core._device import DeviceCollector
from ophyd_async.core._mock_signal_utils import callback_on_mock_put, set_mock_value


@pytest.fixture
def ad_standard_det_factory(
    RE: RunEngine,
    static_path_provider,
) -> Callable[[StandardDetector, int], StandardDetector]:
    def generate_ad_standard_det(
        ad_standard_detector_class, number=1
    ) -> StandardDetector:
        # Dynamically generate a name based on the class of detector
        detector_name = ad_standard_detector_class.__name__
        if detector_name.endswith("Detector"):
            detector_name = detector_name[: -len("Detector")]

        with DeviceCollector(mock=True):
            test_adstandard_det = ad_standard_detector_class(
                f"{detector_name.upper()}{number}:",
                static_path_provider,
                name=f"test_ad{detector_name.lower()}{number}",
            )

        def on_set_file_path_callback(value, **kwargs):
            if os.path.exists(value):
                set_mock_value(test_adstandard_det.hdf.file_path_exists, True)
                set_mock_value(
                    test_adstandard_det.hdf.full_file_name,
                    f"{value}/{static_path_provider._filename_provider(device_name=test_adstandard_det.name)}.h5",
                )

        callback_on_mock_put(
            test_adstandard_det.hdf.file_path, on_set_file_path_callback
        )

        # Set some sensible defaults to mimic a real detector setup
        set_mock_value(test_adstandard_det.drv.acquire_time, (number - 0.2))
        set_mock_value(test_adstandard_det.drv.acquire_period, float(number))
        set_mock_value(test_adstandard_det.hdf.capture, True)

        # Set number of frames per chunk and frame dimensions to something reasonable
        set_mock_value(test_adstandard_det.hdf.num_frames_chunks, 1)
        set_mock_value(test_adstandard_det.drv.array_size_x, (9 + number))
        set_mock_value(test_adstandard_det.drv.array_size_y, (9 + number))

        return test_adstandard_det

    return generate_ad_standard_det
