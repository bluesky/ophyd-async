import asyncio
from typing import Literal, TypeVar, get_args

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

AravisControllerT = TypeVar("AravisControllerT", bound="AravisController")


class AravisController(adcore.ADBaseController[AravisDriverIO]):
    GPIO_NUMBER = Literal[1, 2, 3, 4]

    def __init__(
        self,
        driver: AravisDriverIO,
        good_states: frozenset[adcore.DetectorState] = adcore.DEFAULT_GOOD_STATES,
        gpio_number: GPIO_NUMBER = 1,
    ) -> None:
        super().__init__(driver, good_states=good_states)
        self.gpio_number = gpio_number

    @classmethod
    def controller_and_drv(
        cls: type[AravisControllerT],
        prefix: str,
        good_states: frozenset[adcore.DetectorState] = adcore.DEFAULT_GOOD_STATES,
        name: str = "",
        gpio_number: GPIO_NUMBER = 1,
    ) -> tuple[AravisControllerT, AravisDriverIO]:
        driver_cls = get_args(cls.__orig_bases__[0])[0]  # type: ignore
        driver = driver_cls(prefix, name=name)
        controller = cls(driver, good_states=good_states, gpio_number=gpio_number)
        return controller, driver

    def get_deadtime(self, exposure: float | None) -> float:
        return _HIGHEST_POSSIBLE_DEADTIME

    async def prepare(self, trigger_info: TriggerInfo):
        if trigger_info.total_number_of_triggers == 0:
            image_mode = adcore.ImageMode.continuous
        else:
            image_mode = adcore.ImageMode.multiple
        if (exposure := trigger_info.livetime) is not None:
            await self._driver.acquire_time.set(exposure)

        trigger_mode, trigger_source = self._get_trigger_info(trigger_info.trigger)
        # trigger mode must be set first and on it's own!
        await self._driver.trigger_mode.set(trigger_mode)

        await asyncio.gather(
            self._driver.trigger_source.set(trigger_source),
            self._driver.num_images.set(trigger_info.total_number_of_triggers),
            self._driver.image_mode.set(image_mode),
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
            return AravisTriggerMode.off, AravisTriggerSource.freerun
        else:
            return (AravisTriggerMode.on, f"Line{self.gpio_number}")  # type: ignore

    def get_external_trigger_gpio(self):
        return self.gpio_number

    def set_external_trigger_gpio(self, gpio_number: GPIO_NUMBER):
        supported_gpio_numbers = get_args(AravisController.GPIO_NUMBER)
        if gpio_number not in supported_gpio_numbers:
            raise ValueError(
                f"{self.__class__.__name__} only supports the following GPIO "
                f"indices: {supported_gpio_numbers} but was asked to "
                f"use {gpio_number}"
            )
        self.gpio_number = gpio_number
