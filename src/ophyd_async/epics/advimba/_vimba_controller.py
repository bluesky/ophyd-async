import asyncio

from ophyd_async.core import (
    AsyncStatus,
    DetectorController,
    DetectorTrigger,
    TriggerInfo,
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


class VimbaController(DetectorController):
    def __init__(
        self,
        driver: VimbaDriverIO,
    ) -> None:
        self._drv = driver
        self._arm_status: AsyncStatus | None = None

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001

    async def prepare(self, trigger_info: TriggerInfo):
        await asyncio.gather(
            self._drv.trigger_mode.set(TRIGGER_MODE[trigger_info.trigger]),
            self._drv.exposure_mode.set(EXPOSE_OUT_MODE[trigger_info.trigger]),
            self._drv.num_images.set(trigger_info.total_number_of_triggers),
            self._drv.image_mode.set(adcore.ImageMode.MULTIPLE),
        )
        if trigger_info.livetime is not None and trigger_info.trigger not in [
            DetectorTrigger.VARIABLE_GATE,
            DetectorTrigger.CONSTANT_GATE,
        ]:
            await self._drv.acquire_time.set(trigger_info.livetime)
        if trigger_info.trigger != DetectorTrigger.INTERNAL:
            self._drv.trigger_source.set(VimbaTriggerSource.LINE1)
        else:
            self._drv.trigger_source.set(VimbaTriggerSource.FREERUN)

    async def arm(self):
        self._arm_status = await adcore.start_acquiring_driver_and_ensure_status(
            self._drv
        )

    async def wait_for_idle(self):
        if self._arm_status:
            await self._arm_status

    async def disarm(self):
        await adcore.stop_busy_record(self._drv.acquire, False, timeout=1)
