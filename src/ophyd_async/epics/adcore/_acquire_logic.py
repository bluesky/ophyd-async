import asyncio

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DetectorAcquireLogic,
    SignalR,
    set_and_wait_for_other_value,
    wait_for_value,
)
from ophyd_async.epics.core import stop_busy_record, wait_for_good_state

from ._io import ADBaseIO, ADState, NDCircularBuffIO


class ADAcquireLogic(DetectorAcquireLogic):
    def __init__(
        self, driver: ADBaseIO, driver_armed_signal: SignalR[bool] | None = None
    ):
        self.driver = driver
        if driver_armed_signal is not None:
            self.driver_armed_signal = driver_armed_signal
        else:
            self.driver_armed_signal = driver.acquire
        self.acquire_status: AsyncStatus | None = None

    async def start_acquiring(self):
        self.acquire_status = await set_and_wait_for_other_value(
            set_signal=self.driver.acquire,
            set_value=True,
            match_signal=self.driver_armed_signal,
            match_value=True,
            wait_for_set_completion=False,
            timeout=DEFAULT_TIMEOUT,
        )

    async def wait_for_idle(self):
        if self.acquire_status:
            await self.acquire_status
        await wait_for_good_state(
            self.driver.detector_state,
            {ADState.IDLE, ADState.ABORTED},
            timeout=DEFAULT_TIMEOUT,
        )

    async def ensure_stopped(self):
        await stop_busy_record(self.driver.acquire)


class ADContAcqAcquireLogic(DetectorAcquireLogic):
    """Gate continuous acquisition after skipping potentially dirty frames.

    :param driver: The continuously acquiring detector driver
    :param cb_plugin: The circular buffer plugin gating downstream plugins
    :param num_frames_to_skip:
        Non-negative number of incoming frames to skip before each gate opening.
        Defaults to 0, which opens the gate immediately.
    """

    def __init__(
        self,
        driver: ADBaseIO,
        cb_plugin: NDCircularBuffIO,
        num_frames_to_skip: int = 0,
    ):
        self.driver = driver
        self.cb_plugin = cb_plugin
        self.num_frames_to_skip = num_frames_to_skip

    async def start_acquiring(self):
        num_frames_to_skip = self.num_frames_to_skip
        if num_frames_to_skip:
            initial_count, acquire_period = await asyncio.gather(
                self.cb_plugin.array_counter.get_value(cached=False),
                self.driver.acquire_period.get_value(),
            )
            # Count arrivals at the gate, not driver frames or monitor callbacks.
            await wait_for_value(
                self.cb_plugin.array_counter,
                lambda count: count >= initial_count + num_frames_to_skip,
                timeout=num_frames_to_skip * acquire_period + DEFAULT_TIMEOUT,
            )
        await self.cb_plugin.trigger_.set(True)

    async def wait_for_idle(self):
        num_images, acquire_period = await asyncio.gather(
            self.cb_plugin.post_count.get_value(),
            self.driver.acquire_period.get_value(),
        )

        await wait_for_value(
            self.cb_plugin.trigger_,
            False,
            timeout=num_images * acquire_period + DEFAULT_TIMEOUT,
        )

    async def ensure_stopped(self):
        await stop_busy_record(self.cb_plugin.capture)
