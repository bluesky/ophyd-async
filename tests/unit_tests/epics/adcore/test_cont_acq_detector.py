import asyncio
import re
from unittest.mock import patch

import pytest

from ophyd_async.core import (
    DetectorTrigger,
    StaticPathProvider,
    TriggerInfo,
    callback_on_mock_put,
    init_devices,
    set_mock_value,
)
from ophyd_async.epics import adcore
from ophyd_async.testing import wait_for_pending_wakeups


@pytest.fixture
async def cont_acq_detector() -> adcore.AreaDetector[adcore.ADBaseIO]:
    async with init_devices(mock=True):
        det = adcore.ContAcqDetector(prefix="PREFIX:")

    set_mock_value(
        det.driver.image_mode,
        adcore.ADImageMode.CONTINUOUS,
    )
    set_mock_value(det.driver.acquire_time, 0.8)
    set_mock_value(det.driver.acquire_period, 1.0)
    set_mock_value(det.driver.acquire, True)
    # The CB plugin Trigger is a busy record that resets itself to False once the
    # requested frames are buffered; simulate that immediate completion.
    callback_on_mock_put(det.cb.trigger_, lambda value: False)
    return det


async def test_cont_acq_controller_invalid_trigger_mode(
    cont_acq_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    trigger_info = TriggerInfo(trigger=DetectorTrigger.EXTERNAL_EDGE)
    with pytest.raises(
        ValueError,
        match=re.escape(
            "Trigger type DetectorTrigger.EXTERNAL_EDGE not supported by 'det', "
            "supported types are: [INTERNAL]"
        ),
    ):
        await cont_acq_detector.prepare(trigger_info)


ERROR_MESSAGE = (
    "Driver must be acquiring in continuous mode to use the cont acq interface"
)


async def test_cont_acq_controller_not_in_continuous_mode(
    cont_acq_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    set_mock_value(cont_acq_detector.driver.image_mode, adcore.ADImageMode.SINGLE)
    with pytest.raises(RuntimeError, match=ERROR_MESSAGE):
        await cont_acq_detector.trigger()


async def test_cont_acq_controller_not_acquiring(
    cont_acq_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    set_mock_value(cont_acq_detector.driver.acquire, False)
    with pytest.raises(RuntimeError, match=ERROR_MESSAGE):
        await cont_acq_detector.trigger()


async def test_cont_acq_controller_invalid_exposure_time(
    cont_acq_detector: adcore.AreaDetector[adcore.ADBaseIO],
):
    with pytest.raises(
        ValueError,
        match=re.escape(
            "Detector exposure time currently set to 0.8, but requested exposure is 1.0"
        ),
    ):
        await cont_acq_detector.prepare(TriggerInfo(livetime=1.0))


@pytest.mark.parametrize(
    "num_frames_to_skip, dirty_deltas",
    [(0, ()), (1, (1,)), (2, (1, 2)), (2, (4,))],
)
@pytest.mark.parametrize(
    "exposures_per_collection, proc_suffix", [(1, None), (5, "PROC:")]
)
async def test_cont_acq_skips_dirty_frames(
    num_frames_to_skip: int,
    dirty_deltas: tuple[int, ...],
    exposures_per_collection: int,
    proc_suffix: str | None,
    static_path_provider: StaticPathProvider,
):
    """Check frame skipping before collecting data from a free-running detector.

    The driver keeps exposing between scan steps, so the next arriving frame
    may have started exposing while the sample was moving. The circular buffer
    (CB) gate prevents those potentially dirty frames from reaching downstream
    plugins until the configured number of arrivals has passed.

    The two parameterizations cover independent aspects of this behavior:

    - `num_frames_to_skip, dirty_deltas`: skip 0, 1, or 2 incoming frames.
      `dirty_deltas` contains CB counter offsets from the current trigger's
      starting value. `(1, 2)` represents consecutive arrivals; `(4,)` models
      a monitor update that combines several arrivals, jumping past the
      two-frame threshold. An empty tuple means the gate opens immediately.
    - `exposures_per_collection, proc_suffix`: `(1, None)` uses one raw exposure
      per saved output image (a collection), without a process plugin.
      `(5, "PROC:")` configures a process plugin to combine five raw exposures
      into one collection, for example by averaging. The mock simulates the
      resulting writer count, not the plugin's filtering calculation. Skipped
      frames must not contribute to those five exposures.

    Each combination is triggered twice with starting CB counts of 100 and 200
    to check that every trigger uses a fresh baseline. Duplicate CB values and
    driver counter changes must not advance the skip. After the gate opens,
    only subsequent frames are forwarded, and completion requires enough
    exposures for one collection, advancing the saved collection index by one.
    """
    async with init_devices(mock=True):
        det = adcore.ContAcqDetector(
            "PREFIX:",
            adcore.ADWriterFactory.hdf(static_path_provider),
            proc_suffix=proc_suffix,
            num_frames_to_skip=num_frames_to_skip,
        )
    cb = det.get_plugin("cb", adcore.NDCircularBuffIO)
    writer = det.get_plugin("hdf", adcore.NDFileHDF5IO)
    set_mock_value(det.driver.image_mode, adcore.ADImageMode.CONTINUOUS)
    set_mock_value(det.driver.acquire, True)
    set_mock_value(det.driver.acquire_time, 0.8)
    set_mock_value(det.driver.acquire_period, 1.0)
    set_mock_value(writer.file_path_exists, True)
    set_mock_value(cb.capture, True)
    set_mock_value(cb.pre_count, 2)

    async def set_pre_count(value: int) -> int:
        # ADCore refuses PreCount changes while capture is active.
        return await cb.pre_count.get_value() if await cb.capture.get_value() else value

    callback_on_mock_put(cb.pre_count, set_pre_count)
    await det.stage()
    assert not await cb.capture.get_value()
    assert await det.driver.acquire.get_value()
    await det.prepare(TriggerInfo(exposures_per_collection=exposures_per_collection))

    forwarded: list[int] = []

    async def receive_frame(counter: int) -> None:
        # The CB processes the frame before publishing its counter readback.
        if await cb.trigger_.get_value():
            forwarded.append(counter)
            if len(forwarded) == await cb.post_count.get_value():
                set_mock_value(
                    writer.num_captured, await writer.num_captured.get_value() + 1
                )
                set_mock_value(cb.trigger_, False)
        set_mock_value(cb.array_counter, counter)
        await wait_for_pending_wakeups(max_yields=100)

    for collection, initial_count in enumerate((100, 200), start=1):
        # Frames arriving between triggers must not count towards the next skip.
        set_mock_value(cb.array_counter, initial_count)
        forwarded.clear()

        status = det.trigger()
        await wait_for_pending_wakeups(max_yields=100)
        assert await cb.capture.get_value()
        assert await cb.pre_count.get_value() == 0
        assert await cb.trigger_.get_value() == (num_frames_to_skip == 0)
        assert not status.done

        if num_frames_to_skip:
            # Driver progress and repeated CB monitor values are not new CB frames.
            set_mock_value(det.driver.array_counter, initial_count + 10)
            set_mock_value(cb.array_counter, initial_count)
            await wait_for_pending_wakeups(max_yields=100)
            assert not await cb.trigger_.get_value()

        for delta in dirty_deltas:
            await receive_frame(initial_count + delta)
            assert await cb.trigger_.get_value() == (delta >= num_frames_to_skip)
            assert forwarded == []
            assert await det.get_index() == collection - 1

        last_dirty_count = initial_count + (dirty_deltas[-1] if dirty_deltas else 0)
        clean_frames = list(
            range(last_dirty_count + 1, last_dirty_count + exposures_per_collection + 1)
        )
        for counter in clean_frames:
            await receive_frame(counter)
        assert status.done
        await status
        assert forwarded == clean_frames
        assert await det.get_index() == collection

    await det.unstage()
    assert not await cb.capture.get_value()
    assert await det.driver.acquire.get_value()


@pytest.mark.parametrize("cancel", [False, True])
async def test_cont_acq_interrupted_frame_wait_keeps_gate_closed(cancel: bool):
    driver = adcore.ADBaseIO("PREFIX:DRV:")
    cb = adcore.NDCircularBuffIO("PREFIX:CB:")
    async with init_devices(mock=True):
        det = adcore.AreaDetector(
            driver,
            acquire_logic=adcore.ADContAcqAcquireLogic(
                driver, cb, num_frames_to_skip=2
            ),
            trigger_logic=adcore.ADContAcqTriggerLogic(driver, cb, None),
            plugins={"cb": cb},
        )
    set_mock_value(driver.image_mode, adcore.ADImageMode.CONTINUOUS)
    set_mock_value(driver.acquire, True)
    set_mock_value(driver.acquire_period, 0.01)
    set_mock_value(cb.array_counter, 100)
    await det.stage()
    await det.prepare(TriggerInfo())

    with patch("ophyd_async.epics.adcore._acquire_logic.DEFAULT_TIMEOUT", 0.01):
        if cancel:
            status = det.trigger()
            await wait_for_pending_wakeups(max_yields=100)
            status.task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await status
        else:
            with pytest.raises(TimeoutError):
                await det.trigger()

    set_mock_value(cb.array_counter, 102)
    await wait_for_pending_wakeups(max_yields=100)
    assert not await cb.trigger_.get_value()
    assert await driver.acquire.get_value()
    await det.unstage()
    assert not await cb.capture.get_value()
