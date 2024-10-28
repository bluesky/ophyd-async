import asyncio

from ophyd_async.core import DetectorController, DetectorTrigger
from ophyd_async.core._detector import TriggerInfo
from ophyd_async.core._status import AsyncStatus
from ophyd_async.epics import adcore

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
            self._drv.image_mode.set(adcore.ImageMode.multiple),
        )
        if trigger_info.livetime is not None and trigger_info.trigger not in [
            DetectorTrigger.variable_gate,
            DetectorTrigger.constant_gate,
        ]:
            await self._drv.acquire_time.set(trigger_info.livetime)
        if trigger_info.trigger != DetectorTrigger.internal:
            self._drv.trigger_source.set(VimbaTriggerSource.line1)
        else:
            self._drv.trigger_source.set(VimbaTriggerSource.freerun)

    async def arm(self):
        self._arm_status = await adcore.start_acquiring_driver_and_ensure_status(
            self._drv
        )

    async def wait_for_idle(self):
        if self._arm_status:
            await self._arm_status

    async def disarm(self):
        await adcore.stop_busy_record(self._drv.acquire, False, timeout=1)
