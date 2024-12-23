import asyncio
from typing import Generic, TypeVar

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DetectorController,
    DetectorTrigger,
    TriggerInfo,
    set_and_wait_for_value,
)

from ._core_io import ADBaseIO, DetectorState
from ._utils import ImageMode, stop_busy_record

# Default set of states that we should consider "good" i.e. the acquisition
#  is complete and went well
DEFAULT_GOOD_STATES: frozenset[DetectorState] = frozenset(
    [DetectorState.IDLE, DetectorState.ABORTED]
)

ADBaseIOT = TypeVar("ADBaseIOT", bound=ADBaseIO)
ADBaseControllerT = TypeVar("ADBaseControllerT", bound="ADBaseController")


class ADBaseController(DetectorController, Generic[ADBaseIOT]):
    def __init__(
        self,
        driver: ADBaseIOT,
        good_states: frozenset[DetectorState] = DEFAULT_GOOD_STATES,
    ) -> None:
        self.driver = driver
        self.good_states = good_states
        self.frame_timeout = DEFAULT_TIMEOUT
        self._arm_status: AsyncStatus | None = None

    async def prepare(self, trigger_info: TriggerInfo) -> None:
        assert (
            trigger_info.trigger == DetectorTrigger.INTERNAL
        ), "fly scanning (i.e. external triggering) is not supported for this device"
        self.frame_timeout = (
            DEFAULT_TIMEOUT + await self.driver.acquire_time.get_value()
        )
        await asyncio.gather(
            self.driver.num_images.set(trigger_info.total_number_of_triggers),
            self.driver.image_mode.set(ImageMode.MULTIPLE),
        )

    async def arm(self):
        self._arm_status = await self.start_acquiring_driver_and_ensure_status()

    async def wait_for_idle(self):
        if self._arm_status:
            await self._arm_status

    async def disarm(self):
        # We can't use caput callback as we already used it in arm() and we can't have
        # 2 or they will deadlock
        await stop_busy_record(self.driver.acquire, False, timeout=1)

    async def set_exposure_time_and_acquire_period_if_supplied(
        self,
        exposure: float | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """
        Sets the exposure time if it is not None and the acquire period to the
        exposure time plus the deadtime. This is expected behavior for most
        AreaDetectors, but some may require more specialized handling.

        Parameters
        ----------
        exposure:
            Desired exposure time, this is a noop if it is None.
        timeout:
            How long to wait for the exposure time and acquire period to be set.
        """
        if exposure is not None:
            full_frame_time = exposure + self.get_deadtime(exposure)
            await asyncio.gather(
                self.driver.acquire_time.set(exposure, timeout=timeout),
                self.driver.acquire_period.set(full_frame_time, timeout=timeout),
            )

    async def start_acquiring_driver_and_ensure_status(self) -> AsyncStatus:
        """
        Start acquiring driver, raising ValueError if the detector is in a bad state.

        This sets driver.acquire to True, and waits for it to be True up to a timeout.
        Then, it checks that the DetectorState PV is in DEFAULT_GOOD_STATES,
        and otherwise raises a ValueError.

        Returns
        -------
        AsyncStatus:
            An AsyncStatus that can be awaited to set driver.acquire to True and perform
            subsequent raising (if applicable) due to detector state.
        """

        status = await set_and_wait_for_value(
            self.driver.acquire,
            True,
            timeout=DEFAULT_TIMEOUT,
            wait_for_set_completion=False,
        )

        async def complete_acquisition() -> None:
            """NOTE: possible race condition here between the callback from
            set_and_wait_for_value and the detector state updating."""
            await status
            state = await self.driver.detector_state.get_value()
            if state not in self.good_states:
                raise ValueError(
                    f"Final detector state {state.value} not "
                    "in valid end states: {self.good_states}"
                )

        return AsyncStatus(complete_acquisition())
