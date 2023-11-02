import asyncio
from typing import Optional

from ophyd_async.core import (
    AsyncStatus,
    DetectorControl,
    DetectorTrigger,
    set_and_wait_for_value,
)

from ..drivers.pilatus_driver import PilatusDriver, TriggerMode
from ..utils import ImageMode, stop_busy_record

TRIGGER_MODE = {
    DetectorTrigger.internal: TriggerMode.internal,
    DetectorTrigger.constant_gate: TriggerMode.ext_enable,
    DetectorTrigger.variable_gate: TriggerMode.ext_enable,
}


class PilatusController(DetectorControl):
    def __init__(self, driver: PilatusDriver) -> None:
        self.driver = driver

    def get_deadtime(self, exposure: float) -> float:
        return 0.001

    async def arm(
        self,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        num: int = 0,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        await asyncio.gather(
            self.driver.trigger_mode.set(TRIGGER_MODE[trigger]),
            self.driver.num_images.set(2**31 - 1 if num == 0 else num),
            self.driver.image_mode.set(ImageMode.multiple),
        )
        return await set_and_wait_for_value(self.driver.acquire, True)

    async def disarm(self):
        await stop_busy_record(self.driver.acquire, False, timeout=1)
