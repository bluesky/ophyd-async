import asyncio
from typing import Optional

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DetectorControl,
    DetectorTrigger,
    set_and_wait_for_value,
)

from ..drivers.ad_driver import ADDriver, ImageMode


class ADSimController(DetectorControl):
    def __init__(self, driver: ADDriver) -> None:
        self.driver = driver

    def get_deadtime(self, exposure: float) -> float:
        return 0.002

    async def arm(
        self,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        num: int = 0,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        assert (
            trigger == DetectorTrigger.internal
        ), "fly scanning (i.e. external triggering) is not supported for this device"
        frame_timeout = DEFAULT_TIMEOUT + await self.driver.acquire_time.get_value()
        await asyncio.gather(
            self.driver.num_images.set(num),
            self.driver.image_mode.set(ImageMode.multiple),
        )
        return await set_and_wait_for_value(
            self.driver.acquire, True, timeout=frame_timeout
        )

    async def disarm(self):
        # We can't use caput callback as we already used it in arm() and we can't have
        # 2 or they will deadlock
        await set_and_wait_for_value(
            self.driver.acquire, False, with_callback=False, timeout=1
        )
