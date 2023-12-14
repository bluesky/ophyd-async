import asyncio
from typing import Optional, Set

from ophyd_async.core import AsyncStatus, DetectorControl, DetectorTrigger
from ophyd_async.epics.areadetector.drivers.ad_base import (
    DEFAULT_GOOD_STATES,
    DetectorState,
    start_acquiring_driver_and_ensure_status,
)

from ..drivers.pilatus_driver import PilatusDriver, TriggerMode
from ..utils import ImageMode, stop_busy_record

TRIGGER_MODE = {
    DetectorTrigger.internal: TriggerMode.internal,
    DetectorTrigger.constant_gate: TriggerMode.ext_enable,
    DetectorTrigger.variable_gate: TriggerMode.ext_enable,
}


class PilatusController(DetectorControl):
    def __init__(
        self,
        driver: PilatusDriver,
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
            self.driver.num_images.set(999_999 if num == 0 else num),
            self.driver.image_mode.set(ImageMode.multiple),
        )
        return await start_acquiring_driver_and_ensure_status(
            self.driver, good_states=self.good_states
        )

    async def disarm(self):
        await stop_busy_record(self.driver.acquire, False, timeout=1)
