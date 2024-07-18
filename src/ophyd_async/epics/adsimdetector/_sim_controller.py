import asyncio
from typing import Optional, Set

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DetectorControl,
    DetectorTrigger,
)
from ophyd_async.epics import adcore


class SimController(DetectorControl):
    def __init__(
        self,
        driver: adcore.ADBase,
        good_states: Set[adcore.DetectorState] = set(adcore.DEFAULT_GOOD_STATES),
    ) -> None:
        self.driver = driver
        self.good_states = good_states

    def get_deadtime(self, exposure: float) -> float:
        return 0.002

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        assert (
            trigger == DetectorTrigger.internal
        ), "fly scanning (i.e. external triggering) is not supported for this device"
        frame_timeout = DEFAULT_TIMEOUT + await self.driver.acquire_time.get_value()
        await asyncio.gather(
            self.driver.num_images.set(num),
            self.driver.image_mode.set(adcore.ImageMode.multiple),
        )
        return await adcore.start_acquiring_driver_and_ensure_status(
            self.driver, good_states=self.good_states, timeout=frame_timeout
        )

    async def disarm(self):
        # We can't use caput callback as we already used it in arm() and we can't have
        # 2 or they will deadlock
        await adcore.stop_busy_record(self.driver.acquire, False, timeout=1)
