import os
from collections.abc import Callable

import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import init_devices
from ophyd_async.epics import adcore
from ophyd_async.testing import callback_on_mock_put, set_mock_value


@pytest.fixture
def ad_standard_det_factory(
    RE: RunEngine,
    static_path_provider,
) -> Callable[
    [type[adcore.AreaDetector], type[adcore.ADWriter], int], adcore.AreaDetector
]:
    def generate_ad_standard_det(
        detector_cls: type[adcore.AreaDetector],
        writer_cls: type[adcore.ADWriter] = adcore.ADHDFWriter,
        number=1,
        **kwargs,
    ) -> adcore.AreaDetector:
        # Dynamically generate a name based on the class of controller
        detector_name = detector_cls.__name__
        if detector_name.endswith("Detector"):
            detector_name = detector_name[: -len("Detector")]

        with init_devices(mock=True):
            prefix = f"{detector_name.upper()}{number}:"
            name = f"test_ad{detector_name.lower()}{number}"

            test_adstandard_det = detector_cls(
                prefix,
                static_path_provider,
                # The inner areaDetector class wants the instantaiated object,
                # but the outward facing classes want a writer class type
                writer_cls=writer_cls,  # type: ignore
                name=name,
            )

        def on_set_file_path_callback(value: str, wait: bool = True):
            if os.path.exists(value):
                set_mock_value(test_adstandard_det.fileio.file_path_exists, True)
                set_mock_value(
                    test_adstandard_det.fileio.full_file_name,
                    f"{value}/{static_path_provider._filename_provider(device_name=test_adstandard_det.name)}{test_adstandard_det._writer._file_extension}",
                )

        callback_on_mock_put(
            test_adstandard_det.fileio.file_path, on_set_file_path_callback
        )

        # Set some sensible defaults to mimic a real detector setup
        set_mock_value(test_adstandard_det.driver.acquire_time, (number - 0.2))
        set_mock_value(test_adstandard_det.driver.acquire_period, float(number))
        set_mock_value(test_adstandard_det.fileio.capture, True)

        # Set number of frames per chunk and frame dimensions to something reasonable
        set_mock_value(test_adstandard_det.driver.array_size_x, (9 + number))
        set_mock_value(test_adstandard_det.driver.array_size_y, (9 + number))

        if isinstance(test_adstandard_det.fileio, adcore.NDFileHDFIO):
            set_mock_value(test_adstandard_det.fileio.num_frames_chunks, 1)

        return test_adstandard_det

    return generate_ad_standard_det
