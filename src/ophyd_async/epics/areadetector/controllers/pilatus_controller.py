import asyncio
from typing import Optional

from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.detector import DetectorControl, DetectorTrigger
from ophyd_async.epics.areadetector.drivers.ad_base import (
    start_acquiring_driver_and_ensure_status,
)
from ophyd_async.epics.areadetector.drivers.pilatus_driver import (
    PilatusDriver,
    PilatusTriggerMode,
)
from ophyd_async.epics.areadetector.utils import ImageMode, stop_busy_record


class PilatusController(DetectorControl):
    _supported_trigger_types = {
        DetectorTrigger.internal: PilatusTriggerMode.internal,
        DetectorTrigger.constant_gate: PilatusTriggerMode.ext_enable,
        DetectorTrigger.variable_gate: PilatusTriggerMode.ext_enable,
    }

    def __init__(
        self,
        driver: PilatusDriver,
    ) -> None:
        self._drv = driver

    def get_deadtime(self, exposure: float) -> float:
        # Cite: https://media.dectris.com/User_Manual-PILATUS2-V1_4.pdf
        """The required minimum time difference between ExpPeriod and ExpTime
        (readout time) is 2.28 ms"""
        return 2.28e-3

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        if exposure is not None:
            await self._drv.acquire_time.set(exposure)
        await asyncio.gather(
            self._drv.trigger_mode.set(self._get_trigger_mode(trigger)),
            self._drv.num_images.set(999_999 if num == 0 else num),
            self._drv.image_mode.set(ImageMode.multiple),
        )
        return await start_acquiring_driver_and_ensure_status(self._drv)

    @classmethod
    def _get_trigger_mode(cls, trigger: DetectorTrigger) -> PilatusTriggerMode:
        if trigger not in cls._supported_trigger_types.keys():
            raise ValueError(
                f"{cls.__name__} only supports the following trigger "
                f"types: {cls._supported_trigger_types.keys()} but was asked to "
                f"use {trigger}"
            )
        return cls._supported_trigger_types[trigger]

    async def disarm(self):
        await stop_busy_record(self._drv.acquire, False, timeout=1)
