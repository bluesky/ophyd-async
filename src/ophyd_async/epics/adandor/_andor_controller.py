import asyncio

from ophyd_async.core import (
    AsyncStatus,
    DetectorController,
    DetectorTrigger,
    TriggerInfo,
    set_and_wait_for_value,
)
from ophyd_async.epics.adcore import (
    set_exposure_time_and_acquire_period_if_supplied,
    stop_busy_record,
)

from ._andor_io import Andor2DriverIO, Andor2TriggerMode, ImageMode

_MIN_DEAD_TIME = 0.1
_MAX_NUM_IMAGE = 999_999


class Andor2Controller(DetectorController):
    def __init__(
        self,
        driver: Andor2DriverIO,
    ) -> None:
        self._drv = driver
        self._arm_status: AsyncStatus | None = None

    def get_deadtime(self, exposure: float | None) -> float:
        return _MIN_DEAD_TIME + (exposure or 0)

    async def prepare(self, trigger_info: TriggerInfo):
        await set_exposure_time_and_acquire_period_if_supplied(
            self, self._drv, trigger_info.livetime
        )
        await asyncio.gather(
            self._drv.trigger_mode.set(self._get_trigger_mode(trigger_info.trigger)),
            self._drv.num_images.set(
                trigger_info.total_number_of_triggers or _MAX_NUM_IMAGE
            ),
            self._drv.image_mode.set(ImageMode.MULTIPLE),
        )

    async def arm(self):
        self._arm_status = await set_and_wait_for_value(self._drv.acquire, True)

    async def wait_for_idle(self):
        if self._arm_status:
            await self._arm_status

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

    async def disarm(self):
        await stop_busy_record(self._drv.acquire, False, timeout=1)
