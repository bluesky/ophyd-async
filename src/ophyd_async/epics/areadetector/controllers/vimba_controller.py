import asyncio
from typing import Optional, Set

from ophyd_async.core import AsyncStatus, DetectorControl, DetectorTrigger
from ophyd_async.epics.areadetector.drivers.ad_base import (
    DEFAULT_GOOD_STATES,
    DetectorState,
    start_acquiring_driver_and_ensure_status,
)

from ..drivers.vimba_driver import VimbaDriver, ExposeOutMode, OnOff, TriggerSource
from ..utils import ImageMode, stop_busy_record

TRIGGER_MODE = {
    DetectorTrigger.internal: OnOff.off,
    DetectorTrigger.constant_gate: OnOff.on,
    DetectorTrigger.variable_gate: OnOff.on,
    DetectorTrigger.edge_trigger: OnOff.on,
}

EXPOSE_OUT_MODE = {
    DetectorTrigger.internal: ExposeOutMode.timed,
    DetectorTrigger.constant_gate: ExposeOutMode.trigger_width,
    DetectorTrigger.variable_gate: ExposeOutMode.trigger_width,
    DetectorTrigger.edge_trigger: ExposeOutMode.timed,
}


class VimbaController(DetectorControl):
    def __init__(
        self,
        driver: VimbaDriver,
        good_states: Set[DetectorState] = set(DEFAULT_GOOD_STATES),
    ) -> None:
        self.driver = driver
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
            self.driver.trigger_mode.set(TRIGGER_MODE[trigger]),
            self.driver.expose_out_mode.set(EXPOSE_OUT_MODE[trigger]),
            self.driver.num_images.set(999_999 if num == 0 else num),
            self.driver.image_mode.set(ImageMode.multiple),
        )
        if exposure is not None and trigger not in [
            DetectorTrigger.variable_gate,
            DetectorTrigger.constant_gate,
        ]:
            await self.driver.acquire_time.set(exposure)
        if trigger != DetectorTrigger.internal:
            self.driver.trigger_source.set(TriggerSource.line1)
        return await start_acquiring_driver_and_ensure_status(
            self.driver, good_states=self.good_states
        )

    async def disarm(self):
        await self.driver.acquire.set(0)
