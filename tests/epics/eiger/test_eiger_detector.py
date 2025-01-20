from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from ophyd_async.core import DetectorTrigger, init_devices
from ophyd_async.epics.eiger import EigerDetector, EigerTriggerInfo
from ophyd_async.epics.eiger.det_dim_constants import EIGER2_X_16M_SIZE
from ophyd_async.testing import get_mock_put


@pytest.fixture
def detector(RE):
    with init_devices(mock=True):
        detector = EigerDetector("BL03I", MagicMock())
    return detector


def create_eiger_trigger_info():
    return EigerTriggerInfo(
        frame_timeout=None,
        number_of_triggers=1,
        trigger=DetectorTrigger.INTERNAL,
        deadtime=None,
        livetime=None,
        energy_ev=10000,
        exposure_time=1.0,
        detector_distance=1.0,
        omega_start=0.0,
        omega_increment=0.0,
        use_roi_mode=False,
        det_dist_to_beam_converter_path="tests/epics/eiger/test_lookup_table.txt",
        detector_size_constants=EIGER2_X_16M_SIZE,
    )


def test_when_detector_initialised_then_driver_and_odin_have_expected_prefixes(
    detector,
):
    assert "BL03I-EA-EIGER-01:" in detector.drv.arm.source
    assert "BL03I-EA-ODIN-01:FP:" in detector.odin.acquisition_id.source


async def test_when_prepared_with_energy_then_energy_set_on_detector(detector):
    detector._controller.arm = AsyncMock()
    await detector.prepare(create_eiger_trigger_info())

    get_mock_put(detector.drv.photon_energy).assert_called_once_with(10000, wait=ANY)


async def test_set_mx_settings_sets_pvs_correctly(detector):
    detector.detector_params = create_eiger_trigger_info()
    beam_center_x_calculated = detector.detector_params.get_beam_position_pixels(
        detector.detector_params.detector_distance
    )[0]

    assert await detector.drv.beam_centre_x.get_value() != beam_center_x_calculated

    await detector.set_mx_settings_pvs()

    assert await detector.drv.beam_centre_x.get_value() == beam_center_x_calculated
