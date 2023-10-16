import asyncio
from typing import Optional

from ophyd_async.core import (
    AsyncStatus,
    DetectorControl,
    DetectorTrigger,
    set_and_wait_for_value,
)

from ..drivers.ad_aravis_driver import ADAravisDriver, TriggerMode
from ..utils import ImageMode, stop_busy_record


class ADAravisController(DetectorControl):
    def __init__(self, driver: ADAravisDriver) -> None:
        self.driver = driver

    def get_deadtime(self, exposure: float) -> float:
        return 0.0002

    async def arm(
        self,
        mode: DetectorTrigger = DetectorTrigger.internal,
        num: int = 0,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        await asyncio.gather(
            self.driver.set_trigger_source(mode),
            self.driver.trigger_mode.set(TriggerMode.on),
            self.driver.num_images.set(num),
            self.driver.image_mode.set(ImageMode.multiple),
        )
        return await set_and_wait_for_value(self.driver.acquire, True)

    async def disarm(self):
        await stop_busy_record(self.driver.trigger_mode, TriggerMode.off, timeout=1)
        await stop_busy_record(self.driver.acquire, False, timeout=1)
