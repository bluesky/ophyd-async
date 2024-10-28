import asyncio

from ophyd_async.core import DetectorController, DetectorTrigger
from ophyd_async.core._detector import TriggerInfo
from ophyd_async.core._status import AsyncStatus
from ophyd_async.epics import adcore

from ._kinetix_io import KinetixDriverIO, KinetixTriggerMode

KINETIX_TRIGGER_MODE_MAP = {
    DetectorTrigger.internal: KinetixTriggerMode.internal,
    DetectorTrigger.constant_gate: KinetixTriggerMode.gate,
    DetectorTrigger.variable_gate: KinetixTriggerMode.gate,
    DetectorTrigger.edge_trigger: KinetixTriggerMode.edge,
}


class KinetixController(DetectorController):
    def __init__(
        self,
        driver: KinetixDriverIO,
    ) -> None:
        self._drv = driver
        self._arm_status: AsyncStatus | None = None

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001

    async def prepare(self, trigger_info: TriggerInfo):
        await asyncio.gather(
            self._drv.trigger_mode.set(KINETIX_TRIGGER_MODE_MAP[trigger_info.trigger]),
            self._drv.num_images.set(trigger_info.total_number_of_triggers),
            self._drv.image_mode.set(adcore.ImageMode.multiple),
        )
        if trigger_info.livetime is not None and trigger_info.trigger not in [
            DetectorTrigger.variable_gate,
            DetectorTrigger.constant_gate,
        ]:
            await self._drv.acquire_time.set(trigger_info.livetime)

    async def arm(self):
        self._arm_status = await adcore.start_acquiring_driver_and_ensure_status(
            self._drv
        )

    async def wait_for_idle(self):
        if self._arm_status:
            await self._arm_status

    async def disarm(self):
        await adcore.stop_busy_record(self._drv.acquire, False, timeout=1)
