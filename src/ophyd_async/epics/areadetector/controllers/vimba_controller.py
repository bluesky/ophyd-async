import asyncio
from typing import Optional, Set

from ophyd_async.core import AsyncStatus, DetectorControl, DetectorTrigger
from ophyd_async.epics.areadetector.drivers.ad_base import (
    DEFAULT_GOOD_STATES,
    DetectorState,
    start_acquiring_driver_and_ensure_status,
)

from ..drivers.vimba_driver import (
    VimbaDriver,
    VimbaExposeOutMode,
    VimbaOnOff,
    VimbaTriggerSource,
)
from ..utils import ImageMode, stop_busy_record

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
        good_states: Set[DetectorState] = set(DEFAULT_GOOD_STATES),
    ) -> None:
        self._drv = driver
        self.good_states = good_states

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
            self._drv.expose_out_mode.set(EXPOSE_OUT_MODE[trigger]),
            self._drv.num_images.set(num),
            self._drv.image_mode.set(ImageMode.multiple),
        )
        if exposure is not None and trigger not in [
            DetectorTrigger.variable_gate,
            DetectorTrigger.constant_gate,
        ]:
            await self._drv.acquire_time.set(exposure)
        if trigger != DetectorTrigger.internal:
            self._drv.trigger_source.set(VimbaTriggerSource.line1)
        return await start_acquiring_driver_and_ensure_status(
            self._drv, good_states=self.good_states
        )

    async def disarm(self):
        await stop_busy_record(self._drv.acquire, False, timeout=1)
