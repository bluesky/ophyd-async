import asyncio
from typing import Generic, TypeVar

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DetectorController,
    DetectorTrigger,
    TriggerInfo,
    observe_value,
    set_and_wait_for_value,
)

from ._core_io import (
    ADBaseIO,
    ADCallbacks,
    ADState,
    NDCBFlushOnSoftTrgMode,
    NDPluginCBIO,
)
from ._utils import ADImageMode, stop_busy_record

# Default set of states that we should consider "good" i.e. the acquisition
#  is complete and went well
DEFAULT_GOOD_STATES: frozenset[ADState] = frozenset([ADState.IDLE, ADState.ABORTED])

ADBaseIOT = TypeVar("ADBaseIOT", bound=ADBaseIO)
ADBaseControllerT = TypeVar("ADBaseControllerT", bound="ADBaseController")


class ADBaseController(DetectorController, Generic[ADBaseIOT]):
    def __init__(
        self,
        driver: ADBaseIOT,
        good_states: frozenset[ADState] = DEFAULT_GOOD_STATES,
    ) -> None:
        self.driver: ADBaseIOT = driver
        self.good_states = good_states
        self.frame_timeout = DEFAULT_TIMEOUT
        self._arm_status: AsyncStatus | None = None

    async def prepare(self, trigger_info: TriggerInfo) -> None:
        if trigger_info.trigger != DetectorTrigger.INTERNAL:
            msg = (
                "fly scanning (i.e. external triggering) is not supported for this "
                "device"
            )
            raise TypeError(msg)
        self.frame_timeout = (
            DEFAULT_TIMEOUT + await self.driver.acquire_time.get_value()
        )
        await asyncio.gather(
            self.driver.num_images.set(trigger_info.total_number_of_exposures),
            self.driver.image_mode.set(ADImageMode.MULTIPLE),
        )

    async def arm(self):
        self._arm_status = await self.start_acquiring_driver_and_ensure_status()

    async def wait_for_idle(self):
        if self._arm_status and not self._arm_status.done:
            await self._arm_status
        self._arm_status = None

    async def disarm(self):
        # We can't use caput callback as we already used it in arm() and we can't have
        # 2 or they will deadlock
        await stop_busy_record(self.driver.acquire, False)

    async def set_exposure_time_and_acquire_period_if_supplied(
        self,
        exposure: float | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """Set the exposure time and acquire period.

        If exposure is not None, this sets the acquire time to the exposure time
        and sets the acquire period to the exposure time plus the deadtime. This
        is expected behavior for most AreaDetectors, but some may require more
        specialized handling.

        :param exposure: Desired exposure time, this is a noop if it is None.
        :type exposure: How long to wait for the exposure time and acquire
            period to be set.
        """
        if exposure is not None:
            full_frame_time = exposure + self.get_deadtime(exposure)
            await asyncio.gather(
                self.driver.acquire_time.set(exposure, timeout=timeout),
                self.driver.acquire_period.set(full_frame_time, timeout=timeout),
            )

    async def start_acquiring_driver_and_ensure_status(
        self,
        start_timeout: float = DEFAULT_TIMEOUT,
        state_timeout: float = DEFAULT_TIMEOUT,
    ) -> AsyncStatus:
        """Start acquiring driver, raising ValueError if the detector is in a bad state.

        This sets driver.acquire to True, and waits for it to be True up to a timeout.
        Then, it checks that the DetectorState PV is in DEFAULT_GOOD_STATES,
        and otherwise raises a ValueError.


        :param start_timeout:
            Timeout used for waiting for the driver to start
            acquiring.
        :param state_timeout:
            Timeout used for waiting for the detector to be in a good
            state after it stops acquiring.
        :returns AsyncStatus:
            An AsyncStatus that can be awaited to set driver.acquire to True and perform
            subsequent raising (if applicable) due to detector state.

        """
        status = await set_and_wait_for_value(
            self.driver.acquire,
            True,
            timeout=start_timeout,
            wait_for_set_completion=False,
        )

        async def complete_acquisition() -> None:
            await status
            state = None
            try:
                async for state in observe_value(
                    self.driver.detector_state, done_timeout=state_timeout
                ):
                    if state in self.good_states:
                        return
            except asyncio.TimeoutError as exc:
                if state is not None:
                    raise ValueError(
                        f"Final detector state {state.value} not in valid end "
                        f"states: {self.good_states}"
                    ) from exc
                else:
                    # No updates from the detector, something else is wrong
                    raise asyncio.TimeoutError(
                        "Could not monitor detector state: "
                        + self.driver.detector_state.source
                    ) from exc

        return AsyncStatus(complete_acquisition())


class ADBaseContAcqController(ADBaseController[ADBaseIO]):
    """Continuous acquisition interface for an AreaDetector."""

    def __init__(self, driver: ADBaseIO, cb_plugin: NDPluginCBIO) -> None:
        self.cb_plugin = cb_plugin
        super().__init__(driver)

    def get_deadtime(self, exposure):
        # For now just set this to something until we can decide how to pass this in
        return 0.001

    async def ensure_acquisition_settings_valid(
        self, trigger_info: TriggerInfo
    ) -> None:
        """Ensure the trigger mode is valid for the detector."""
        if trigger_info.trigger != DetectorTrigger.INTERNAL:
            # Note that not all detectors will use the `DetectorTrigger` enum
            raise TypeError(
                "The continuous acq interface only supports internal triggering."
            )

        # Not all detectors allow for changing exposure times during an acquisition,
        # so in this least-common-denominator implementation check to see if
        # exposure time matches the current exposure time.
        exposure_time = await self.driver.acquire_time.get_value()
        if trigger_info.livetime is not None and trigger_info.livetime != exposure_time:
            raise ValueError(
                f"Detector exposure time currently set to {exposure_time}, "
                f"but requested exposure is {trigger_info.livetime}"
            )

    async def ensure_in_continuous_acquisition_mode(self) -> None:
        """Ensure the detector is in continuous acquisition mode."""
        image_mode = await self.driver.image_mode.get_value()
        acquiring = await self.driver.acquire.get_value()

        if image_mode != ADImageMode.CONTINUOUS or not acquiring:
            raise RuntimeError(
                "Driver must be acquiring in continuous mode to use the "
                "cont acq interface"
            )

    async def prepare(self, trigger_info: TriggerInfo) -> None:
        # These are broken out into seperate functions to make it easier to
        # override them in subclasses, for example if you want `prepare` to
        # setup the detector in continuous mode if it isn't already (for now,
        # we assume it already is). If your detector uses different enums
        # for `ImageMode` or `DetectorTrigger`, you should also override these.
        await self.ensure_acquisition_settings_valid(trigger_info)
        await self.ensure_in_continuous_acquisition_mode()

        # Configure the CB plugin to collect the correct number of triggers
        await asyncio.gather(
            self.cb_plugin.enable_callbacks.set(ADCallbacks.ENABLE),
            self.cb_plugin.pre_count.set(0),
            self.cb_plugin.post_count.set(trigger_info.total_number_of_exposures),
            self.cb_plugin.preset_trigger_count.set(1),
            self.cb_plugin.flush_on_soft_trg.set(NDCBFlushOnSoftTrgMode.ON_NEW_IMAGE),
        )

    async def arm(self) -> None:
        # Start the CB plugin's capture, and cache it in the arm status attr
        self._arm_status = await set_and_wait_for_value(
            self.cb_plugin.capture,
            True,
            timeout=DEFAULT_TIMEOUT,
            wait_for_set_completion=False,
        )

        # Send the trigger to begin acquisition
        await self.cb_plugin.trigger.set(True, wait=False)

    async def disarm(self) -> None:
        await stop_busy_record(self.cb_plugin.capture, False)
        if self._arm_status and not self._arm_status.done:
            await self._arm_status
        self._arm_status = None
