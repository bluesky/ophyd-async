import asyncio
from typing import Optional

from ophyd_async.core import (
    AsyncStatus,
    DetectorControl,
    DetectorTrigger,
    set_and_wait_for_other_value,
)

from ._eiger_io import EigerDriverIO, EigerTriggerMode

EIGER_TRIGGER_MODE_MAP = {
    DetectorTrigger.internal: EigerTriggerMode.internal,
    DetectorTrigger.constant_gate: EigerTriggerMode.gate,
    DetectorTrigger.variable_gate: EigerTriggerMode.gate,
    DetectorTrigger.edge_trigger: EigerTriggerMode.edge,
}


class EigerController(DetectorControl):
    def __init__(
        self,
        driver: EigerDriverIO,
    ) -> None:
        self._drv = driver

    def get_deadtime(self, exposure: float) -> float:
        return 0.0001

    @AsyncStatus.wrap
    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = None,
    ):
        await asyncio.gather(
            self._drv.trigger_mode.set(EIGER_TRIGGER_MODE_MAP[trigger]),
            self._drv.num_images.set(num),
            self._drv.acquire_time.set(exposure),
            self._drv.acquire_period.set(exposure),
        )

        await set_and_wait_for_other_value(self._drv.arm, 1, self._drv.state, "ready")

    async def disarm(self):
        await self._drv.disarm.set(1)
