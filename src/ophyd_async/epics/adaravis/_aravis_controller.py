import asyncio
from typing import Literal, cast

from ophyd_async.core import (
    DetectorTrigger,
    TriggerInfo,
)
from ophyd_async.epics import adcore

from ._aravis_io import AravisDriverIO, AravisTriggerMode, AravisTriggerSource

# The deadtime of an ADaravis controller varies depending on the exact model of camera.
# Ideally we would maximize performance by dynamically retrieving the deadtime at
# runtime. See https://github.com/bluesky/ophyd-async/issues/308
_HIGHEST_POSSIBLE_DEADTIME = 1961e-6


class AravisController(adcore.ADBaseController):
    GPIO_NUMBER = Literal[1, 2, 3, 4]

    def __init__(self, driver: AravisDriverIO, gpio_number: GPIO_NUMBER) -> None:
        super().__init__(driver)
        self.gpio_number = gpio_number

    @property
    def driver(self) -> AravisDriverIO:
        return cast(AravisDriverIO, self._driver)

    def get_deadtime(self, exposure: float | None) -> float:
        return _HIGHEST_POSSIBLE_DEADTIME

    async def prepare(self, trigger_info: TriggerInfo):
        if trigger_info.total_number_of_triggers == 0:
            image_mode = adcore.ImageMode.continuous
        else:
            image_mode = adcore.ImageMode.multiple
        if (exposure := trigger_info.livetime) is not None:
            await self.driver.acquire_time.set(exposure)

        trigger_mode, trigger_source = self._get_trigger_info(trigger_info.trigger)
        # trigger mode must be set first and on it's own!
        await self.driver.trigger_mode.set(trigger_mode)

        await asyncio.gather(
            self.driver.trigger_source.set(trigger_source),
            self.driver.num_images.set(trigger_info.total_number_of_triggers),
            self.driver.image_mode.set(image_mode),
        )

    def _get_trigger_info(
        self, trigger: DetectorTrigger
    ) -> tuple[AravisTriggerMode, AravisTriggerSource]:
        supported_trigger_types = (
            DetectorTrigger.constant_gate,
            DetectorTrigger.edge_trigger,
            DetectorTrigger.internal,
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
            return (AravisTriggerMode.on, f"Line{self.gpio_number}")  # type: ignore
