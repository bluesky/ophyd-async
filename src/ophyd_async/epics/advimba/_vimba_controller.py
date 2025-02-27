import asyncio

from ophyd_async.core import (
    DetectorTrigger,
    TriggerInfo,
    set_and_wait_for_value,
)
from ophyd_async.epics import adcore

from ._vimba_io import VimbaDriverIO, VimbaExposeOutMode, VimbaOnOff, VimbaTriggerSource

TRIGGER_MODE = {
    DetectorTrigger.INTERNAL: VimbaOnOff.OFF,
    DetectorTrigger.CONSTANT_GATE: VimbaOnOff.ON,
    DetectorTrigger.VARIABLE_GATE: VimbaOnOff.ON,
    DetectorTrigger.EDGE_TRIGGER: VimbaOnOff.ON,
}

EXPOSE_OUT_MODE = {
    DetectorTrigger.INTERNAL: VimbaExposeOutMode.TIMED,
    DetectorTrigger.CONSTANT_GATE: VimbaExposeOutMode.TRIGGER_WIDTH,
    DetectorTrigger.VARIABLE_GATE: VimbaExposeOutMode.TRIGGER_WIDTH,
    DetectorTrigger.EDGE_TRIGGER: VimbaExposeOutMode.TIMED,
}


class VimbaController(adcore.ADBaseController[VimbaDriverIO]):
    """Controller for the Vimba detector."""

    def __init__(
        self,
        driver: VimbaDriverIO,
        good_states: frozenset[adcore.ADState] = adcore.DEFAULT_GOOD_STATES,
    ) -> None:
        super().__init__(driver, good_states=good_states)

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001

    async def prepare(self, trigger_info: TriggerInfo):
        await asyncio.gather(
            self.driver.trigger_mode.set(TRIGGER_MODE[trigger_info.trigger]),
            self.driver.exposure_mode.set(EXPOSE_OUT_MODE[trigger_info.trigger]),
            self.driver.num_images.set(trigger_info.total_number_of_triggers),
            self.driver.image_mode.set(adcore.ImageMode.MULTIPLE),
        )
        if trigger_info.livetime is not None and trigger_info.trigger not in [
            DetectorTrigger.VARIABLE_GATE,
            DetectorTrigger.CONSTANT_GATE,
        ]:
            await self.driver.acquire_time.set(trigger_info.livetime)
        if trigger_info.trigger != DetectorTrigger.INTERNAL:
            self.driver.trigger_source.set(VimbaTriggerSource.LINE1)
        else:
            self.driver.trigger_source.set(VimbaTriggerSource.FREERUN)


class ContAcqVimbaController(adcore.ADBaseContAcqController[VimbaDriverIO]):
    """Continuous acquisition controller for the Vimba detector."""

    def __init__(self, cb_plugin_prefix: str, driver: VimbaDriverIO) -> None:
        super().__init__(cb_plugin_prefix, driver)

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001

    async def prepare(self, trigger_info: TriggerInfo) -> None:
        # Since the ADVimba driver does allow for changing exposure time
        # during continuous acquisition, we can set it here.
        if trigger_info.livetime is not None:
            await self.driver.acquire_time.set(trigger_info.livetime)
            await self.driver.acquire_period.set(
                trigger_info.livetime + self.get_deadtime(trigger_info.livetime)
            )

        # Check if we are acquiring in continuous mode, if not then start to.
        image_mode = await self.driver.image_mode.get_value()
        acquiring = await self.driver.acquire.get_value()
        if image_mode != adcore.ImageMode.CONTINUOUS or not acquiring:
            await asyncio.gather(
                self.driver.trigger_mode.set(VimbaOnOff.OFF),
                self.driver.trigger_source.set(VimbaTriggerSource.FREERUN),
                self.driver.exposure_mode.set(VimbaExposeOutMode.TIMED),
                self.driver.image_mode.set(adcore.ImageMode.CONTINUOUS),
            )

            await set_and_wait_for_value(self.driver.acquire, True, timeout=1)

        # Call superclass prepare method to configure CB plugin
        await super().prepare(trigger_info)
