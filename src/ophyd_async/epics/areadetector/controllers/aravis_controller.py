import asyncio
from typing import Literal, Optional, Tuple

from ophyd_async.core import (
    AsyncStatus,
    DetectorControl,
    DetectorTrigger,
    set_and_wait_for_value,
)
from ophyd_async.epics.areadetector.drivers.aravis_driver import (
    AravisDriver,
    AravisTriggerMode,
    AravisTriggerSource,
)
from ophyd_async.epics.areadetector.utils import ImageMode, stop_busy_record

# The deadtime of an ADaravis controller varies depending on the exact model of camera.
# Ideally we would maximize performance by dynamically retrieving the deadtime at
# runtime. See https://github.com/bluesky/ophyd-async/issues/308
_HIGHEST_POSSIBLE_DEADTIME = 1961e-6


class AravisController(DetectorControl):
    GPIO_NUMBER = Literal[1, 2, 3, 4]

    def __init__(self, driver: AravisDriver, gpio_number: GPIO_NUMBER) -> None:
        self._drv = driver
        self.gpio_number = gpio_number

    def get_deadtime(self, exposure: float) -> float:
        return _HIGHEST_POSSIBLE_DEADTIME

    async def arm(
        self,
        num: int = 0,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = None,
    ) -> AsyncStatus:
        if num == 0:
            image_mode = ImageMode.continuous
        else:
            image_mode = ImageMode.multiple
        if exposure is not None:
            await self._drv.acquire_time.set(exposure)

        trigger_mode, trigger_source = self._get_trigger_info(trigger)
        # trigger mode must be set first and on it's own!
        await self._drv.trigger_mode.set(trigger_mode)

        await asyncio.gather(
            self._drv.trigger_source.set(trigger_source),
            self._drv.num_images.set(num),
            self._drv.image_mode.set(image_mode),
        )

        status = await set_and_wait_for_value(self._drv.acquire, True)
        return status

    def _get_trigger_info(
        self, trigger: DetectorTrigger
    ) -> Tuple[AravisTriggerMode, AravisTriggerSource]:
        supported_trigger_types = (
            DetectorTrigger.constant_gate,
            DetectorTrigger.edge_trigger,
        )
        if trigger not in supported_trigger_types:
            raise ValueError(
                f"{self.__class__.__name__} only supports the following trigger "
                f"types: {supported_trigger_types} but was asked to "
                f"use {trigger}"
            )
        if trigger == DetectorTrigger.internal:
            return AravisTriggerMode.off, "Freerun"
        else:
            return (AravisTriggerMode.on, f"Line{self.gpio_number}")

    async def disarm(self):
        await stop_busy_record(self._drv.acquire, False, timeout=1)
