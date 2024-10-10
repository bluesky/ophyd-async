import asyncio
from typing import cast

from ophyd_async.core import DetectorTrigger
from ophyd_async.core._detector import TriggerInfo
from ophyd_async.epics import adcore

from ._kinetix_io import KinetixDriverIO, KinetixTriggerMode

KINETIX_TRIGGER_MODE_MAP = {
    DetectorTrigger.internal: KinetixTriggerMode.internal,
    DetectorTrigger.constant_gate: KinetixTriggerMode.gate,
    DetectorTrigger.variable_gate: KinetixTriggerMode.gate,
    DetectorTrigger.edge_trigger: KinetixTriggerMode.edge,
}


class KinetixController(adcore.ADBaseController):
    def __init__(
        self,
        driver: KinetixDriverIO,
    ) -> None:
        super().__init__(driver)

    @property
    def driver(self) -> KinetixDriverIO:
        return cast(KinetixDriverIO, self._driver)

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001

    async def prepare(self, trigger_info: TriggerInfo):
        await asyncio.gather(
            self.driver.trigger_mode.set(
                KINETIX_TRIGGER_MODE_MAP[trigger_info.trigger]
            ),
            self.driver.num_images.set(trigger_info.number),
            self.driver.image_mode.set(adcore.ImageMode.multiple),
        )
        if trigger_info.livetime is not None and trigger_info.trigger not in [
            DetectorTrigger.variable_gate,
            DetectorTrigger.constant_gate,
        ]:
            await self.driver.acquire_time.set(trigger_info.livetime)
