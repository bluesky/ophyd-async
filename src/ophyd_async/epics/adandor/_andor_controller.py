import asyncio

from ophyd_async.core import (
    DetectorTrigger,
    TriggerInfo,
)
from ophyd_async.epics import adcore

from ._andor_io import Andor2DriverIO, Andor2TriggerMode

_MIN_DEAD_TIME = 0.1
_MAX_NUM_IMAGE = 999_999


class Andor2Controller(adcore.ADBaseController[Andor2DriverIO]):
    """For controlling the Andor 2 detector."""

    def __init__(
        self,
        driver: Andor2DriverIO,
        good_states: frozenset[adcore.ADState] = adcore.DEFAULT_GOOD_STATES,
    ) -> None:
        super().__init__(driver, good_states=good_states)

    def get_deadtime(self, exposure: float | None) -> float:
        return _MIN_DEAD_TIME + (exposure or 0)

    async def prepare(self, trigger_info: TriggerInfo):
        await self.set_exposure_time_and_acquire_period_if_supplied(
            trigger_info.livetime
        )
        await asyncio.gather(
            self.driver.trigger_mode.set(self._get_trigger_mode(trigger_info.trigger)),
            self.driver.num_images.set(
                trigger_info.total_number_of_exposures or _MAX_NUM_IMAGE
            ),
            self.driver.image_mode.set(adcore.ImageMode.MULTIPLE),
        )

    def _get_trigger_mode(self, trigger: DetectorTrigger) -> Andor2TriggerMode:
        supported_trigger_types = {
            DetectorTrigger.INTERNAL: Andor2TriggerMode.INTERNAL,
            DetectorTrigger.EDGE_TRIGGER: Andor2TriggerMode.EXT_TRIGGER,
        }
        if trigger not in supported_trigger_types:
            raise ValueError(
                f"{self.__class__.__name__} only supports the following trigger "
                f"types: {supported_trigger_types} but was asked to "
                f"use {trigger}"
            )
        return supported_trigger_types[trigger]
