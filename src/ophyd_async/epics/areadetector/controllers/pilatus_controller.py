import asyncio

from ophyd_async.core import AsyncStatus, DetectorControl, DetectorTrigger
from ophyd_async.core._detector import DetectorControl, DetectorTrigger
from ophyd_async.core._signal.signal import set_and_wait_for_value, wait_for_value
from ophyd_async.epics.areadetector.utils import ImageMode

from ..drivers.pilatus_driver import PilatusDriver, TriggerMode

TRIGGER_MODE = {
    DetectorTrigger.internal: TriggerMode.internal,
    DetectorTrigger.constant_gate: TriggerMode.ext_enable,
    DetectorTrigger.variable_gate: TriggerMode.ext_enable,
}


class PilatusController(DetectorControl):
    def __init__(self, drv: PilatusDriver) -> None:
        self.driver = drv

    async def get_deadtime(self, exposure: float) -> float:
        return 0.002

    async def arm(
        self, mode: DetectorTrigger = DetectorTrigger.internal, num: int = 0
    ) -> AsyncStatus:
        await asyncio.gather(
            self.driver.trigger_mode.set(TRIGGER_MODE[mode]),
            self.driver.num_images.set(num),
            self.driver.image_mode.set(ImageMode.multiple),
        )
        return await set_and_wait_for_value(self.driver.acquire, True)

    async def disarm(self):
        # wait=False means don't caput callback. We can't use caput callback as we
        # already used it in arm() and we can't have 2 or they will deadlock
        await self.driver.acquire.set(0, wait=False)
        await wait_for_value(self.driver.acquire, False, timeout=1)
