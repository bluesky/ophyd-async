from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DetectorArmLogic,
    SignalR,
    set_and_wait_for_other_value,
    set_and_wait_for_value,
)
from ophyd_async.epics.core import stop_busy_record, wait_for_good_state

from ._io import ADBaseIO, ADState, NDCircularBuffIO


class ADArmLogic(DetectorArmLogic):
    def __init__(
        self, driver: ADBaseIO, driver_armed_signal: SignalR[bool] | None = None
    ):
        self.driver = driver
        if driver_armed_signal is not None:
            self.driver_armed_signal = driver_armed_signal
        else:
            self.driver_armed_signal = driver.acquire
        self.acquire_status: AsyncStatus | None = None

    async def arm(self):
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

    async def disarm(self):
        await stop_busy_record(self.driver.acquire)


class ADContAcqArmLogic(DetectorArmLogic):
    def __init__(self, driver: ADBaseIO, cb_plugin: NDCircularBuffIO):
        self.driver = driver
        self.cb_plugin = cb_plugin
        self.acquire_status: AsyncStatus | None = None

    async def arm(self):
        self.acquire_status = await set_and_wait_for_value(
            self.cb_plugin.capture,
            True,
            wait_for_set_completion=False,
            timeout=DEFAULT_TIMEOUT,
        )

    async def wait_for_idle(self):
        if self.acquire_status:
            await self.acquire_status

    async def disarm(self):
        await stop_busy_record(self.cb_plugin.capture)
