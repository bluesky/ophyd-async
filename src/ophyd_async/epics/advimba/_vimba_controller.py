import asyncio
from typing import Optional

from ophyd_async.core import AsyncStatus, DetectorControl, DetectorTrigger
from ophyd_async.epics import ImageMode, stop_busy_record
from ophyd_async.epics.adcore import start_acquiring_driver_and_ensure_status

from ._vimba_driver import (VimbaDriver, VimbaExposeOutMode, VimbaOnOff,
                            VimbaTriggerSource)

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


class VimbaController(DetectorControl):
    def __init__(
        self,
        driver: VimbaDriver,
    ) -> None:
        self._drv = driver

    def get_deadtime(self, exposure: float) -> float:
        return 0.001

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        await asyncio.gather(
            self._drv.trigger_mode.set(TRIGGER_MODE[trigger]),
            self._drv.expose_mode.set(EXPOSE_OUT_MODE[trigger]),
            self._drv.num_images.set(num),
            self._drv.image_mode.set(ImageMode.multiple),
        )
        if exposure is not None and trigger not in [
            DetectorTrigger.variable_gate,
            DetectorTrigger.constant_gate,
        ]:
            await self._drv.acquire_time.set(exposure)
        if trigger != DetectorTrigger.internal:
            self._drv.trig_source.set(VimbaTriggerSource.line1)
        else:
            self._drv.trig_source.set(VimbaTriggerSource.freerun)
        return await start_acquiring_driver_and_ensure_status(self._drv)

    async def disarm(self):
        await stop_busy_record(self._drv.acquire, False, timeout=1)
