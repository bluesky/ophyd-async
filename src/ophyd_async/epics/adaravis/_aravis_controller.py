import asyncio

from ophyd_async.core import DetectorTrigger, TriggerInfo
from ophyd_async.epics import adcore

from ._aravis_io import AravisDriverIO, AravisTriggerMode, AravisTriggerSource

# The deadtime of an ADaravis controller varies depending on the exact model of camera.
# Ideally we would maximize performance by dynamically retrieving the deadtime at
# runtime. See https://github.com/bluesky/ophyd-async/issues/308
_HIGHEST_POSSIBLE_DEADTIME = 1961e-6


class AravisController(adcore.ADBaseController[AravisDriverIO]):
    """`DetectorController` for an `AravisDriverIO`."""

    def get_deadtime(self, exposure: float | None) -> float:
        return _HIGHEST_POSSIBLE_DEADTIME

    async def prepare(self, trigger_info: TriggerInfo) -> None:
        if (exposure := trigger_info.livetime) is not None:
            await self.driver.acquire_time.set(exposure)

        if trigger_info.trigger is DetectorTrigger.INTERNAL:
            # Set trigger mode off to ignore the trigger source
            await self.driver.trigger_mode.set(AravisTriggerMode.OFF)
        elif trigger_info.trigger in {
            DetectorTrigger.CONSTANT_GATE,
            DetectorTrigger.EDGE_TRIGGER,
        }:
            # Trigger on the rising edge of Line1
            # trigger mode must be set first and on it's own!
            await self.driver.trigger_mode.set(AravisTriggerMode.ON)
            await self.driver.trigger_source.set(AravisTriggerSource.LINE1)
        else:
            raise ValueError(f"ADAravis does not support {trigger_info.trigger}")

        if trigger_info.total_number_of_exposures == 0:
            image_mode = adcore.ADImageMode.CONTINUOUS
        else:
            image_mode = adcore.ADImageMode.MULTIPLE
        await asyncio.gather(
            self.driver.num_images.set(trigger_info.total_number_of_exposures),
            self.driver.image_mode.set(image_mode),
        )
