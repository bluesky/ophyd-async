import asyncio

from ophyd_async.core import DetectorTrigger
from ophyd_async.core._detector import TriggerInfo
from ophyd_async.epics import adcore
from ophyd_async.epics.adcore._core_io import DetectorState
from ophyd_async.epics.adcore._core_logic import DEFAULT_GOOD_STATES

from ._kinetix_io import KinetixDriverIO, KinetixTriggerMode

KINETIX_TRIGGER_MODE_MAP = {
    DetectorTrigger.internal: KinetixTriggerMode.internal,
    DetectorTrigger.constant_gate: KinetixTriggerMode.gate,
    DetectorTrigger.variable_gate: KinetixTriggerMode.gate,
    DetectorTrigger.edge_trigger: KinetixTriggerMode.edge,
}


class KinetixController(adcore.ADBaseController[KinetixDriverIO]):
    def __init__(
        self,
        driver: KinetixDriverIO,
        good_states: frozenset[DetectorState] = DEFAULT_GOOD_STATES,
    ) -> None:
        super().__init__(driver, good_states=good_states)

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001

    async def prepare(self, trigger_info: TriggerInfo):
        await asyncio.gather(
            self._driver.trigger_mode.set(
                KINETIX_TRIGGER_MODE_MAP[trigger_info.trigger]
            ),
            self._driver.num_images.set(trigger_info.total_number_of_triggers),
            self._driver.image_mode.set(adcore.ImageMode.multiple),
        )
        if trigger_info.livetime is not None and trigger_info.trigger not in [
            DetectorTrigger.variable_gate,
            DetectorTrigger.constant_gate,
        ]:
            await self._driver.acquire_time.set(trigger_info.livetime)
