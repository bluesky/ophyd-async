from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DetectorAcquireLogic,
    SignalR,
    set_and_wait_for_other_value,
    set_and_wait_for_value,
)
from ophyd_async.epics.core import stop_busy_record, wait_for_good_state

from ._io import ADBaseIO, ADState, NDCircularBuffIO


class ADAcquireLogic(DetectorAcquireLogic):
    """Arm and disarm an areaDetector driver.

    :param driver: The areaDetector driver to arm.
    :param driver_armed_signal:
        The signal to watch for the driver having armed, if it is not `acquire`.
    :param wait_for_plugins:
        Whether the detector should wait for its plugins to drain before it
        reports acquisition as complete. `WaitForPlugins` makes the driver's
        `AcquireBusy` wait for the number of queued arrays to reach zero, and
        `wait_for_idle` blocks on the `acquire` put callback, so turning it on
        is what makes a step scan read plugin scalars for the frame it just
        took rather than the one before. Defaults to on, since racing is
        silent and the wait costs nothing when a file writer is the slowest
        thing in the chain anyway. Turn it off for a detector whose plugin
        chain must not gate acquisition.
    """

    def __init__(
        self,
        driver: ADBaseIO,
        driver_armed_signal: SignalR[bool] | None = None,
        wait_for_plugins: bool = True,
    ):
        self.driver = driver
        if driver_armed_signal is not None:
            self.driver_armed_signal = driver_armed_signal
        else:
            self.driver_armed_signal = driver.acquire
        self.wait_for_plugins = wait_for_plugins
        self.acquire_status: AsyncStatus | None = None

    async def ensure_ready(self):
        # Stop first: WaitForPlugins is latched and has no _RBV, so set it once
        # per scan while the driver is known to be idle rather than on the
        # latency path before every arm. Always written, never left at whatever
        # the IOC happened to boot with, so a scan does not depend on who
        # touched the PV last.
        await self.ensure_stopped()
        await self.driver.wait_for_plugins.set(self.wait_for_plugins)

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
    """Start and stop capture on a circular buffer, leaving the driver acquiring.

    Deliberately has no `wait_for_plugins` equivalent to [](#ADAcquireLogic).
    That setting gates the driver's `AcquireBusy` going to 0 at the end of an
    acquisition, and here the driver is always acquiring -- there is no such
    transition to wait on. `wait_for_idle` waits on the circular buffer's
    capture instead.
    """

    def __init__(self, driver: ADBaseIO, cb_plugin: NDCircularBuffIO):
        self.driver = driver
        self.cb_plugin = cb_plugin
        self.acquire_status: AsyncStatus | None = None

    async def start_acquiring(self):
        self.acquire_status = await set_and_wait_for_value(
            self.cb_plugin.capture,
            True,
            wait_for_set_completion=False,
            timeout=DEFAULT_TIMEOUT,
        )

    async def wait_for_idle(self):
        if self.acquire_status:
            await self.acquire_status

    async def ensure_stopped(self):
        await stop_busy_record(self.cb_plugin.capture)
