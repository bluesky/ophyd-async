import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ophyd_async.core import DetectorTrigger, TriggerInfo, init_devices
from ophyd_async.fastcs.jungfrau import DetectorStatus, Jungfrau
from ophyd_async.testing import (
    callback_on_mock_put,
    set_mock_value,
)


@pytest.fixture
def jungfrau(RE):
    with init_devices(mock=True):
        detector = Jungfrau("prefix", MagicMock(), "", "", 4, "jungfrau")

    def set_meta_filename_and_id(value, *args, **kwargs):
        set_mock_value(detector.odin.meta_file_name, value)
        set_mock_value(detector.odin.id, value)

    callback_on_mock_put(detector.odin.file_name, set_meta_filename_and_id)

    detector._writer._path_provider.return_value.filename = "filename.h5"  # type: ignore

    set_mock_value(detector.odin.meta_active, "Active")
    set_mock_value(detector.odin.capture_rbv, "Capturing")
    set_mock_value(detector.odin.meta_writing, "Writing")
    return detector


@pytest.mark.parametrize(
    "trigger_info, match",
    [
        (
            TriggerInfo(trigger=DetectorTrigger.CONSTANT_GATE, deadtime=1),
            "The trigger method can only be called with internal or edge triggering",
        ),
        (
            TriggerInfo(trigger=DetectorTrigger.INTERNAL),
            "Must set TriggerInfo.Livetime for internal trigger mode",
        ),
        (
            TriggerInfo(livetime=1, deadtime=0.96),
            "Period between frames (exposure time - deadtime)*",
        ),
    ],
)
async def test_prepare_val_error_on_bad_trigger_info(
    trigger_info: TriggerInfo, match: str, jungfrau: Jungfrau
):
    with pytest.raises(
        ValueError,
        match=match,
    ):
        await jungfrau.prepare(trigger_info)


async def test_prepare_warn_on_small_exposure(jungfrau: Jungfrau, caplog):
    bad_trigger_info = TriggerInfo(livetime=1e-6)
    with caplog.at_level(logging.WARNING):
        await jungfrau.prepare(bad_trigger_info)
    assert "Exposure time shorter than 2μs is not recommended" in caplog.messages


async def test_prepare_error_on_bad_no_of_event(
    jungfrau: Jungfrau,
):
    bad_trigger_info = TriggerInfo(number_of_events=[2], livetime=1e-3)
    with pytest.raises(TypeError, match="Number of events must be an integer"):
        await jungfrau.prepare(bad_trigger_info)


async def test_good_prepare(jungfrau: Jungfrau):
    good_trigger_info = TriggerInfo(livetime=1e-3)
    await jungfrau.prepare(good_trigger_info)


async def test_arm(jungfrau: Jungfrau):
    jungfrau.drv.acquisition_start.trigger = AsyncMock()
    await jungfrau._controller.arm()
    jungfrau.drv.acquisition_start.trigger.assert_called_once()


@patch("ophyd_async.fastcs.jungfrau._controller.wait_for_value")
async def test_wait_for_idle(mock_wait_for_value: AsyncMock, jungfrau: Jungfrau):
    await jungfrau._controller.wait_for_idle()
    mock_wait_for_value.assert_called_once_with(
        jungfrau.drv.detector_status, DetectorStatus.IDLE, timeout=10.0
    )


async def test_disarm(jungfrau: Jungfrau):
    jungfrau.drv.acquisition_stop.trigger = AsyncMock()
    await jungfrau._controller.disarm()
    jungfrau.drv.acquisition_stop.trigger.assert_called_once()
