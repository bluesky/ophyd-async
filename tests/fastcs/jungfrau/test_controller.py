import logging
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import DetectorTrigger, TriggerInfo, init_devices
from ophyd_async.fastcs.jungfrau import AcquisitionType, DetectorStatus, Jungfrau
from ophyd_async.fastcs.jungfrau._signals import (
    JungfrauTriggerMode,  # noqa: PLC2701
    PedestalMode,  # noqa: PLC2701
)
from ophyd_async.testing import (
    callback_on_mock_put,
    set_mock_value,
)


@pytest.fixture
def jungfrau(RE: RunEngine):
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
            TriggerInfo(),
            "Must set TriggerInfo.livetime",
        ),
        (
            TriggerInfo(trigger=DetectorTrigger.INTERNAL, number_of_events=10),
            "Number of events must be set to 1 in internal trigger mode during "
            "standard acquisitions.",
        ),
        (
            TriggerInfo(
                trigger=DetectorTrigger.EDGE_TRIGGER,
                exposures_per_event=10,
                deadtime=1,
                livetime=2,
            ),
            "Exposures per event must be set to 1 in edge trigger mode "
            "during standard acquisitions.",
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
    jungfrau.drv.pedestal_mode_state.set = AsyncMock()
    jungfrau.drv.acquisition_type.set = AsyncMock()
    await jungfrau._controller.disarm()
    jungfrau.drv.acquisition_stop.trigger.assert_called_once()
    jungfrau.drv.pedestal_mode_state.set.assert_awaited_once_with(PedestalMode.OFF)
    jungfrau.drv.acquisition_type.set.assert_awaited_once_with(AcquisitionType.STANDARD)


async def test_signals_set_in_pedestal_mode(jungfrau: Jungfrau):
    await jungfrau.drv.acquisition_type.set(AcquisitionType.PEDESTAL)
    frames_and_events = 10
    good_trigger_info = TriggerInfo(
        livetime=1e-3,
        number_of_events=frames_and_events * 2,
        exposures_per_event=frames_and_events,
        trigger=DetectorTrigger.INTERNAL,
    )
    await jungfrau.prepare(good_trigger_info)
    assert await jungfrau.drv.pedestal_mode_frames.get_value() == frames_and_events
    assert await jungfrau.drv.pedestal_mode_loops.get_value() == frames_and_events


async def test_signals_set_in_standard_internal_mode(jungfrau: Jungfrau):
    jungfrau.drv.pedestal_mode_frames = AsyncMock()
    jungfrau.drv.pedestal_mode_loops = AsyncMock()
    exp_per_event = 10
    good_trigger_info = TriggerInfo(
        livetime=1e-3,
        exposures_per_event=exp_per_event,
        trigger=DetectorTrigger.INTERNAL,
    )
    await jungfrau.prepare(good_trigger_info)
    assert await jungfrau.drv.frames_per_acq.get_value() == exp_per_event
    jungfrau.drv.pedestal_mode_frames.assert_not_called()
    jungfrau.drv.pedestal_mode_frames.assert_not_called()


async def test_signals_set_in_standard_external_mode(jungfrau: Jungfrau):
    jungfrau.drv.pedestal_mode_frames = AsyncMock()
    jungfrau.drv.pedestal_mode_loops = AsyncMock()
    total_events = 10
    good_trigger_info = TriggerInfo(
        livetime=1e-3,
        number_of_events=total_events,
        trigger=DetectorTrigger.EDGE_TRIGGER,
        deadtime=1,
    )
    await jungfrau.prepare(good_trigger_info)
    assert await jungfrau.drv.frames_per_acq.get_value() == total_events
    jungfrau.drv.pedestal_mode_frames.assert_not_called()
    jungfrau.drv.pedestal_mode_frames.assert_not_called()


async def test_error_in_pedestal_and_external_modes(jungfrau: Jungfrau):
    await jungfrau.drv.acquisition_type.set(AcquisitionType.PEDESTAL)
    with pytest.raises(
        ValueError,
        match="Jungfrau must be triggered internally while in pedestal mode.",
    ):
        await jungfrau.prepare(
            TriggerInfo(livetime=1e-3, trigger=DetectorTrigger.EDGE_TRIGGER, deadtime=1)
        )


async def test_prepare_val_error_if_pedestal_mode_and_odd_number_of_events(
    jungfrau: Jungfrau,
):
    # No. events = pedestal loops * 2, so it should always be even
    await jungfrau.drv.acquisition_type.set(AcquisitionType.PEDESTAL)

    trigger_info = TriggerInfo(livetime=1e-3, deadtime=1)

    with patch("ophyd_async.core._signal.SignalW.set", return_value=None):
        with pytest.raises(
            ValueError,
            match=f"Invalid trigger info for pedestal mode. "
            f"{trigger_info.number_of_events=} must be divisible by two. "
            f"Was create_jungfrau_pedestal_triggering_info used?",
        ):
            await jungfrau.prepare(trigger_info)


async def test_prepare_pedestal_mode_sets_trigger_mode_before_pedestal_mode(
    jungfrau: Jungfrau,
):
    await jungfrau.drv.acquisition_type.set(AcquisitionType.PEDESTAL)
    trigger_info = TriggerInfo(
        livetime=1e-3,
        number_of_events=4,
        deadtime=1,
    )
    parent_mock = MagicMock()
    jungfrau.drv.pedestal_mode_state.set = AsyncMock()
    jungfrau.drv.trigger_mode.set = AsyncMock()
    parent_mock.attach_mock(jungfrau.drv.pedestal_mode_state.set, "pedestal_mode_state")
    parent_mock.attach_mock(jungfrau.drv.trigger_mode.set, "trigger_mode")
    await jungfrau.prepare(trigger_info)
    assert parent_mock.mock_calls == [
        call.trigger_mode(JungfrauTriggerMode.INTERNAL),
        call.pedestal_mode_state(PedestalMode.ON),
    ]
