import asyncio
from typing import Set

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorControl,
    DetectorTrigger,
)
from ophyd_async.core._detector import TriggerInfo
from ophyd_async.epics import adcore


class SimController(DetectorControl):
    def __init__(
        self,
        driver: adcore.ADBaseIO,
        good_states: Set[adcore.DetectorState] = set(adcore.DEFAULT_GOOD_STATES),
    ) -> None:
        self.driver = driver
        self.good_states = good_states
        self.frame_timeout: float

    def get_deadtime(self, exposure: float) -> float:
        return 0.002

    async def prepare(self, trigger_info: TriggerInfo):
        assert (
            trigger_info.trigger == DetectorTrigger.internal
        ), "fly scanning (i.e. external triggering) is not supported for this device"
        self.frame_timeout = (
            DEFAULT_TIMEOUT + await self.driver.acquire_time.get_value()
        )
        await asyncio.gather(
            self.driver.num_images.set(trigger_info.number),
            self.driver.image_mode.set(adcore.ImageMode.multiple),
        )

    def arm(self):
        self._arm_status = adcore.start_acquiring_driver_and_ensure_status(
            self.driver, good_states=self.good_states, timeout=self.frame_timeout
        )

    async def wait_for_armed(self):
        await self._arm_status

    async def disarm(self):
        # We can't use caput callback as we already used it in arm() and we can't have
        # 2 or they will deadlock
        await adcore.stop_busy_record(self.driver.acquire, False, timeout=1)
