import asyncio
from typing import Optional

from ophyd_async.core import (
    AsyncStatus,
    DetectorControl,
    DetectorTrigger,
    set_and_wait_for_value,
)

from ..drivers.ad_aravis_driver import ADAravisDriver, TriggerMode, TriggerSource
from ..utils import ImageMode, stop_busy_record


class ADAravisController(DetectorControl):
    def __init__(self, driver: ADAravisDriver, gpio_number: int) -> None:
        self.driver = driver

        self.gpio_number = gpio_number
        assert gpio_number in {1, 2}, "invalid gpio number"
        self.TRIGGER_SOURCE = {
            DetectorTrigger.internal: TriggerSource.freerun,
            DetectorTrigger.constant_gate: TriggerSource[f"line_{self.gpio_number}"],
            DetectorTrigger.edge_trigger: TriggerSource[f"line_{self.gpio_number}"],
        }

    def get_deadtime(self, exposure: float) -> float:
        return 0.0002

    async def arm(
        self,
        mode: DetectorTrigger = DetectorTrigger.internal,
        num: int = 0,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        if exposure:
            await self.driver.acquire_time.set(exposure)
        await asyncio.gather(
            self.driver.trigger_source.set(self.TRIGGER_SOURCE[mode]),
            self.driver.trigger_mode.set(TriggerMode.on),
            self.driver.num_images.set(num),
            self.driver.image_mode.set(ImageMode.multiple),
        )
        return await set_and_wait_for_value(self.driver.acquire, True)

    async def disarm(self):
        await stop_busy_record(self.driver.acquire, False, timeout=1)
