import asyncio
from typing import Optional, Set

from ophyd_async.core import AsyncStatus, DetectorControl, DetectorTrigger
from ophyd_async.epics.areadetector.drivers.ad_base import (
    DEFAULT_GOOD_STATES,
    DetectorState,
    start_acquiring_driver_and_ensure_status,
)

from ..drivers.kinetix_driver import KinetixDriver, KinetixTriggerMode
from ..utils import ImageMode, stop_busy_record

KINETIX_TRIGGER_MODE_MAP = {
    DetectorTrigger.internal: KinetixTriggerMode.internal,
    DetectorTrigger.constant_gate: KinetixTriggerMode.gate,
    DetectorTrigger.variable_gate: KinetixTriggerMode.gate,
    DetectorTrigger.edge_trigger: KinetixTriggerMode.edge,
}


class KinetixController(DetectorControl):
    def __init__(
        self,
        driver: KinetixDriver,
        good_states: Set[DetectorState] = set(DEFAULT_GOOD_STATES),
    ) -> None:
        self._drv = driver
        self.good_states = good_states

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
            self._drv.image_mode.set(ImageMode.multiple),
        )
        if exposure is not None and trigger not in [
            DetectorTrigger.variable_gate,
            DetectorTrigger.constant_gate,
        ]:
            await self._drv.acquire_time.set(exposure)
        return await start_acquiring_driver_and_ensure_status(
            self._drv, good_states=self.good_states
        )

    async def disarm(self):
        await stop_busy_record(self._drv.acquire, False, timeout=1)
