import asyncio
from typing import Optional

from ophyd_async.core import AsyncStatus, DetectorControl, DetectorTrigger
from ophyd_async.epics import adcore

from ._kinetix_io import KinetixDriverIO, KinetixTriggerMode

KINETIX_TRIGGER_MODE_MAP = {
    DetectorTrigger.internal: KinetixTriggerMode.internal,
    DetectorTrigger.constant_gate: KinetixTriggerMode.gate,
    DetectorTrigger.variable_gate: KinetixTriggerMode.gate,
    DetectorTrigger.edge_trigger: KinetixTriggerMode.edge,
}


class KinetixController(DetectorControl):
    def __init__(
        self,
        driver: KinetixDriverIO,
    ) -> None:
        self._drv = driver

    def get_deadtime(self, exposure: float) -> float:
        return 0.001

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        await asyncio.gather(
            self._drv.trigger_mode.set(KINETIX_TRIGGER_MODE_MAP[trigger]),
            self._drv.num_images.set(num),
            self._drv.image_mode.set(adcore.ImageMode.multiple),
        )
        if exposure is not None and trigger not in [
            DetectorTrigger.variable_gate,
            DetectorTrigger.constant_gate,
        ]:
            await self._drv.acquire_time.set(exposure)
        return await adcore.start_acquiring_driver_and_ensure_status(self._drv)

    async def disarm(self):
        await adcore.stop_busy_record(self._drv.acquire, False, timeout=1)
