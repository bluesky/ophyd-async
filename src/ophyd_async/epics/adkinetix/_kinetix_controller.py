import asyncio

from ophyd_async.core import (
    DetectorTrigger,
    TriggerInfo,
)
from ophyd_async.epics import adcore

from ._kinetix_io import KinetixDriverIO, KinetixTriggerMode

KINETIX_TRIGGER_MODE_MAP = {
    DetectorTrigger.INTERNAL: KinetixTriggerMode.INTERNAL,
    DetectorTrigger.CONSTANT_GATE: KinetixTriggerMode.GATE,
    DetectorTrigger.VARIABLE_GATE: KinetixTriggerMode.GATE,
    DetectorTrigger.EDGE_TRIGGER: KinetixTriggerMode.EDGE,
}


class KinetixController(adcore.ADBaseController[KinetixDriverIO]):
    """Controller for adkinetix detector."""

    def __init__(
        self,
        driver: KinetixDriverIO,
        good_states: frozenset[adcore.ADState] = adcore.DEFAULT_GOOD_STATES,
    ) -> None:
        super().__init__(driver, good_states=good_states)

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001

    async def prepare(self, trigger_info: TriggerInfo):
        await asyncio.gather(
            self.driver.trigger_mode.set(
                KINETIX_TRIGGER_MODE_MAP[trigger_info.trigger]
            ),
            self.driver.num_images.set(trigger_info.total_number_of_exposures),
            self.driver.image_mode.set(adcore.ADImageMode.MULTIPLE),
        )
        if trigger_info.livetime is not None and trigger_info.trigger not in [
            DetectorTrigger.VARIABLE_GATE,
            DetectorTrigger.CONSTANT_GATE,
        ]:
            await self.driver.acquire_time.set(trigger_info.livetime)
