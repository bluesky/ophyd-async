import asyncio
import re
from unittest.mock import call, patch

import pytest

from ophyd_async.core import (
    callback_on_mock_put,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore
from ophyd_async.testing import assert_has_calls


@pytest.fixture
async def adbase_detector() -> adcore.AreaDetector[adcore.ADBaseIO]:
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    async with init_devices(mock=True):
        det = adcore.AreaDetector(driver=driver)
        det.add_detector_logics(adcore.ADAcquireLogic(driver))
    return det


async def test_acquire_logic_trigger_internal_calls_acquire(
    adbase_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    await adbase_detector.trigger()
    assert_has_calls(
        adbase_detector.driver,
        [
            call.acquire.put(True),
        ],
    )


async def test_acquire_logic_when_arming_times_out(
    adbase_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    # This test is meant to exercise wait_task's own internal "didn't match"
    # timeout inside set_and_wait_for_other_value, not the outer "didn't
    # provide an initial value" wait for a first value from match_signal.
    # The mock acquire signal already has an initial value (False) present
    # before this callback ever fires, so the outer got_first_value wait
    # resolves almost immediately regardless of timeout size - but to make
    # that deterministic under CI scheduling jitter (rather than a "photo
    # finish" between the two clocks, which is what originally flaked on
    # Windows CI - see PR #1342), give the callback's delay a large margin
    # over DEFAULT_TIMEOUT. This makes the ratio between "time available for
    # the initial-value observation to land" and "time before the inner
    # match timeout fires" large, without needing to actually wait for the
    # callback to complete (nothing awaits it - only the asyncio.sleep below
    # drains it), so total test wall-clock time stays reasonable.
    async def sleep_for_a_bit(value):
        await asyncio.sleep(1.0)

    callback_on_mock_put(adbase_detector.driver.acquire, sleep_for_a_bit)

    with patch("ophyd_async.epics.adcore._acquire_logic.DEFAULT_TIMEOUT", 0.05):
        with pytest.raises(
            TimeoutError,
            match=re.escape(
                "det-driver-acquire didn't match True in 0.05s, last value False"
            ),
        ):
            await adbase_detector.trigger()

    await asyncio.sleep(1.1)  # Allow background tasks to complete


async def test_acquire_logic_wait_for_idle_in_bad_state(
    adbase_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    set_mock_value(
        adbase_detector.driver.detector_state,
        adcore.ADState.ERROR,
    )
    with patch("ophyd_async.epics.adcore._acquire_logic.DEFAULT_TIMEOUT", 0.05):
        with pytest.raises(ValueError) as exc_info:
            await adbase_detector.trigger()

        # Check that the error message contains the expected information
        error_msg = str(exc_info.value)
        assert "DetectorState_RBV not in a good state: Error: expected" in error_msg
        assert "ADState.IDLE" in error_msg
        assert "ADState.ABORTED" in error_msg


async def test_start_acquiring_driver_and_ensure_status_timing(
    adbase_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    """This test ensures the camera has time to return to a good state.

    Real world application; there is race condition wherein the
    detector has been asked to complete acquisition, but has not yet
    returned to a known good state before the status check.

    """
    set_mock_value(
        adbase_detector.driver.detector_state,
        adcore.ADState.ACQUIRE,
    )

    async def complete_acquire() -> None:
        """Return to idle state, but pretend the detector is slow."""
        await asyncio.sleep(0.1)
        set_mock_value(
            adbase_detector.driver.detector_state,
            adcore.ADState.IDLE,
        )

    await asyncio.gather(adbase_detector.trigger(), complete_acquire())


async def test_acquire_logic_disarm(
    adbase_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    await adbase_detector.unstage()
    assert_has_calls(
        adbase_detector.driver,
        [
            call.acquire.put(False),
        ],
    )


async def bad_observe_value(*args, **kwargs):
    "Stub to simulate a disconnected ``observe_value()``."
    if True:
        raise TimeoutError()
    yield None  # Make it a generator


@patch("ophyd_async.epics.core._util.observe_value", bad_observe_value)
async def test_start_acquiring_driver_and_ensure_status_disconnected(
    adbase_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    """This test ensures the function behaves gracefully if no detector
    states are available.

    """
    with pytest.raises(asyncio.TimeoutError) as exc:
        await adbase_detector.trigger()
    assert (
        str(exc.value)
        == "Could not monitor state: mock+ca://PREFIX:DRV:DetectorState_RBV"
    )
