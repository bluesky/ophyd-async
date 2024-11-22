import asyncio

from ophyd_async.core import DetectorTrigger
from ophyd_async.core._detector import TriggerInfo
from ophyd_async.epics import adcore
from ophyd_async.epics.adcore._core_io import DetectorState
from ophyd_async.epics.adcore._core_logic import DEFAULT_GOOD_STATES

from ._vimba_io import VimbaDriverIO, VimbaExposeOutMode, VimbaOnOff, VimbaTriggerSource

TRIGGER_MODE = {
    DetectorTrigger.internal: VimbaOnOff.off,
    DetectorTrigger.constant_gate: VimbaOnOff.on,
    DetectorTrigger.variable_gate: VimbaOnOff.on,
    DetectorTrigger.edge_trigger: VimbaOnOff.on,
}

EXPOSE_OUT_MODE = {
    DetectorTrigger.internal: VimbaExposeOutMode.timed,
    DetectorTrigger.constant_gate: VimbaExposeOutMode.trigger_width,
    DetectorTrigger.variable_gate: VimbaExposeOutMode.trigger_width,
    DetectorTrigger.edge_trigger: VimbaExposeOutMode.timed,
}


class VimbaController(adcore.ADBaseController[VimbaDriverIO]):
    def __init__(
        self,
        driver: VimbaDriverIO,
        good_states: frozenset[DetectorState] = DEFAULT_GOOD_STATES,
    ) -> None:
        super().__init__(driver, good_states=good_states)

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001

    async def prepare(self, trigger_info: TriggerInfo):
        await asyncio.gather(
            self._driver.trigger_mode.set(TRIGGER_MODE[trigger_info.trigger]),
            self._driver.exposure_mode.set(EXPOSE_OUT_MODE[trigger_info.trigger]),
            self._driver.num_images.set(trigger_info.total_number_of_triggers),
            self._driver.image_mode.set(adcore.ImageMode.multiple),
        )
        if trigger_info.livetime is not None and trigger_info.trigger not in [
            DetectorTrigger.variable_gate,
            DetectorTrigger.constant_gate,
        ]:
            await self._driver.acquire_time.set(trigger_info.livetime)
        if trigger_info.trigger != DetectorTrigger.internal:
            self._driver.trigger_source.set(VimbaTriggerSource.line1)
        else:
            self._driver.trigger_source.set(VimbaTriggerSource.freerun)
