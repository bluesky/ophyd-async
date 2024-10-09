import asyncio

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DatasetDescriber,
    DetectorControl,
    set_and_wait_for_value,
)
from ophyd_async.core._detector import DetectorTrigger, TriggerInfo
from ophyd_async.core._signal import wait_for_value
from ophyd_async.core._utils import T
from ._core_io import DetectorState, ADBaseIO
from ._utils import ImageMode, convert_ad_dtype_to_np, stop_busy_record



# Default set of states that we should consider "good" i.e. the acquisition
#  is complete and went well
DEFAULT_GOOD_STATES: frozenset[DetectorState] = frozenset(
    [DetectorState.Idle, DetectorState.Aborted]
)


class ADBaseDatasetDescriber(DatasetDescriber):
    def __init__(self, driver: ADBaseIO) -> None:
        self._driver = driver

    async def np_datatype(self) -> str:
        return convert_ad_dtype_to_np(await self._driver.data_type.get_value())

    async def shape(self) -> tuple[int, int]:
        shape = await asyncio.gather(
            self._driver.array_size_y.get_value(),
            self._driver.array_size_x.get_value(),
        )
        return shape


class ADBaseController(DetectorControl):
    
    def __init__(
        self,
        driver: ADBaseIO,
        good_states: frozenset[DetectorState] = DEFAULT_GOOD_STATES,
    ) -> None:
        self._driver = driver
        self.good_states = good_states
        self.frame_timeout = DEFAULT_TIMEOUT
        self._arm_status: AsyncStatus | None = None

    @property
    def driver(self) -> ADBaseIO:
        return self._driver

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.002

    async def prepare(self, trigger_info: TriggerInfo):
        assert (
            trigger_info.trigger == DetectorTrigger.internal
        ), "fly scanning (i.e. external triggering) is not supported for this device"
        self.frame_timeout = (
            DEFAULT_TIMEOUT + await self._driver.acquire_time.get_value()
        )
        await asyncio.gather(
            self._driver.num_images.set(trigger_info.number),
            self._driver.image_mode.set(ImageMode.multiple),
        )

    async def arm(self):
        self._arm_status = await self.start_acquiring_driver_and_ensure_status()

    async def wait_for_idle(self):
        if self._arm_status:
            await self._arm_status

    async def disarm(self):
        # We can't use caput callback as we already used it in arm() and we can't have
        # 2 or they will deadlock
        await stop_busy_record(self._driver.acquire, False, timeout=1)


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
                self._driver.acquire_time.set(exposure, timeout=timeout),
                self._driver.acquire_period.set(full_frame_time, timeout=timeout),
            )


    async def start_acquiring_driver_and_ensure_status(self) -> AsyncStatus:
        """
        Start acquiring driver, raising ValueError if the detector is in a bad state.

        This sets driver.acquire to True, and waits for it to be True up to a timeout.
        Then, it checks that the DetectorState PV is in DEFAULT_GOOD_STATES, and otherwise
        raises a ValueError.

        Returns
        -------
        AsyncStatus:
            An AsyncStatus that can be awaited to set driver.acquire to True and perform
            subsequent raising (if applicable) due to detector state.
        """

        status = await set_and_wait_for_value(self._driver.acquire, True, timeout=self.frame_timeout)

        async def complete_acquisition() -> None:
            """NOTE: possible race condition here between the callback from
            set_and_wait_for_value and the detector state updating."""
            await status
            state = await self._driver.detector_state.get_value()
            if state not in self.good_states:
                raise ValueError(
                    f"Final detector state {state} not in valid end states: {self.good_states}"
                )

        return AsyncStatus(complete_acquisition())
