import logging
import re
from unittest.mock import MagicMock, call

import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import (
    DetectorTrigger,
    TriggerInfo,
    callback_on_mock_put,
    get_mock,
    init_devices,
    set_mock_value,
)
from ophyd_async.fastcs.jungfrau import (
    AcquisitionType,
    JungfrauDetector,
    JungfrauTriggerMode,
    PedestalMode,
)


@pytest.fixture
def jungfrau(RE: RunEngine):
    path_provider = MagicMock()
    path_provider.return_value.filename = "filename.h5"  # type: ignore
    with init_devices(mock=True):
        detector = JungfrauDetector("prefix", path_provider, "", "", "jungfrau")

    def set_meta_filename_and_id(value, *args, **kwargs):
        set_mock_value(detector.odin.mw.file_prefix, value)
        set_mock_value(detector.odin.mw.acquisition_id, value)

    callback_on_mock_put(detector.odin.fp.file_prefix, set_meta_filename_and_id)
    set_mock_value(detector.odin.fp.writing, True)
    set_mock_value(detector.odin.mw.writing, True)
    set_mock_value(detector.detector.bit_depth, 8)
    return detector


@pytest.mark.parametrize(
    "trigger_info, match",
    [
        (
            TriggerInfo(trigger=DetectorTrigger.EXTERNAL_LEVEL),
            "Trigger type DetectorTrigger.EXTERNAL_LEVEL not supported by 'jungfrau', "
            "supported types are: [EXTERNAL_EDGE, INTERNAL]",
        ),
        (
            TriggerInfo(livetime=8e-9, deadtime=8e-9),
            "Period between frames (exposure time + deadtime) = 1.6e-08s "
            "cannot be lower than minimum detector deadtime 2e-05",
        ),
    ],
)
async def test_prepare_val_error_on_bad_trigger_info(
    trigger_info: TriggerInfo, match: str, jungfrau: JungfrauDetector
):
    with pytest.raises(
        ValueError,
        match=re.escape(match),
    ):
        await jungfrau.prepare(trigger_info)


async def test_prepare_warn_on_small_exposure(jungfrau: JungfrauDetector, caplog):
    bad_trigger_info = TriggerInfo(livetime=1e-6)
    with caplog.at_level(logging.WARNING):
        await jungfrau.prepare(bad_trigger_info)
    assert "Exposure time shorter than 2μs is not recommended" in caplog.messages


async def test_arm(jungfrau: JungfrauDetector):
    mock = get_mock(jungfrau.detector)
    await jungfrau.prepare(TriggerInfo())
    mock.reset_mock()
    callback_on_mock_put(
        jungfrau.detector.acquisition_start,
        lambda v, wait: set_mock_value(jungfrau.odin.fp.frames_written, 1),
    )
    await jungfrau.trigger()
    assert list(mock.mock_calls) == [call.acquisition_start.put(None, wait=True)]


async def test_disarm(jungfrau: JungfrauDetector):
    await jungfrau.unstage()
    assert list(get_mock(jungfrau.detector).mock_calls) == [
        call.acquisition_stop.put(None, wait=True),
        call.pedestal_mode_state.put(PedestalMode.OFF, wait=True),
    ]


async def test_signals_set_in_pedestal_mode(jungfrau: JungfrauDetector):
    await jungfrau.acquisition_type.set(AcquisitionType.PEDESTAL)
    await jungfrau.detector.pedestal_mode_frames.set(5)
    await jungfrau.detector.pedestal_mode_loops.set(3)
    good_trigger_info = TriggerInfo(
        livetime=1e-3,
        # We make 2 * frames * loops collections
        collections_per_event=2 * 5 * 3,
        trigger=DetectorTrigger.INTERNAL,
    )
    mock = get_mock(jungfrau.detector)
    mock.reset_mock()
    await jungfrau.prepare(good_trigger_info)
    assert list(mock.mock_calls) == [
        call.trigger_mode.put(JungfrauTriggerMode.INTERNAL, wait=True),
        call.period_between_frames.put(0.00102, wait=True),
        call.exposure_time.put(0.001, wait=True),
        call.pedestal_mode_state.put(PedestalMode.ON, wait=True),
    ]


async def test_signals_set_in_standard_internal_mode(jungfrau: JungfrauDetector):
    good_trigger_info = TriggerInfo(
        livetime=1e-3,
        collections_per_event=10,
        trigger=DetectorTrigger.INTERNAL,
    )
    await jungfrau.prepare(good_trigger_info)
    assert list(get_mock(jungfrau.detector).mock_calls) == [
        call.trigger_mode.put(JungfrauTriggerMode.INTERNAL, wait=True),
        call.frames_per_acq.put(10, wait=True),
        call.period_between_frames.put(0.00102, wait=True),
        call.exposure_time.put(0.001, wait=True),
    ]


async def test_signals_set_in_standard_external_mode(jungfrau: JungfrauDetector):
    good_trigger_info = TriggerInfo(
        livetime=1e-3,
        number_of_events=10,
        trigger=DetectorTrigger.EXTERNAL_EDGE,
        deadtime=1,
    )
    await jungfrau.prepare(good_trigger_info)
    assert list(get_mock(jungfrau.detector).mock_calls) == [
        call.trigger_mode.put(JungfrauTriggerMode.EXTERNAL, wait=True),
        call.frames_per_acq.put(10, wait=True),
        call.period_between_frames.put(0.00102, wait=True),
        call.exposure_time.put(0.001, wait=True),
        call.acquisition_start.put(None, wait=True),
    ]


async def test_error_in_pedestal_and_external_modes(jungfrau: JungfrauDetector):
    await jungfrau.acquisition_type.set(AcquisitionType.PEDESTAL)
    with pytest.raises(
        ValueError,
        match="Jungfrau must be triggered internally while in pedestal mode.",
    ):
        await jungfrau.prepare(
            TriggerInfo(
                livetime=1e-3, trigger=DetectorTrigger.EXTERNAL_EDGE, deadtime=1
            )
        )


async def test_prepare_val_error_if_pedestal_mode_and_odd_number_of_events(
    jungfrau: JungfrauDetector,
):
    # No. events = pedestal loops * 2, so it should always be even
    await jungfrau.acquisition_type.set(AcquisitionType.PEDESTAL)
    await jungfrau.detector.pedestal_mode_frames.set(5)
    await jungfrau.detector.pedestal_mode_loops.set(3)

    trigger_info = TriggerInfo(livetime=1e-3, deadtime=1, collections_per_event=15)

    with pytest.raises(
        ValueError,
        match=re.escape(
            "Invalid trigger info for pedestal mode. "
            "Number 15 must be equal to 2 * 5 * 3. "
            "Was create_jungfrau_pedestal_triggering_info used?",
        ),
    ):
        await jungfrau.prepare(trigger_info)
