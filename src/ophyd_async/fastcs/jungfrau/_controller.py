import asyncio
import logging

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorController,
    DetectorTrigger,
    TriggerInfo,
    wait_for_value,
)

from ._signals import (
    JUNGFRAU_TRIGGER_MODE_MAP,
    DetectorStatus,
    JungfrauDriverIO,
)

logger = logging.getLogger("ophyd_async")


class JungfrauController(DetectorController):
    def __init__(self, driver: JungfrauDriverIO):
        self._driver = driver

    def get_deadtime(self, exposure: float | None = None) -> float:
        # See https://rtd.xfel.eu/docs/jungfrau-detector-documentation/en/latest/operation.html
        return 2.1e-6

    async def prepare(self, trigger_info: TriggerInfo) -> None:
        if trigger_info.trigger not in (
            DetectorTrigger.INTERNAL,
            DetectorTrigger.EDGE_TRIGGER,
        ):
            raise ValueError(
                "The trigger method can only be called with internal or edge triggering"
            )
        if not trigger_info.deadtime:
            trigger_info.deadtime = self.get_deadtime()

        coros = []
        if trigger_info.trigger == DetectorTrigger.INTERNAL:
            if not trigger_info.livetime:
                raise ValueError(
                    "Must set TriggerInfo.Livetime for internal trigger mode"
                )
            if trigger_info.livetime < 2e-6:
                logger.warning("Exposure time shorter than 2μs is not recommended")

            period_between_frames = trigger_info.livetime - trigger_info.deadtime

            if period_between_frames < trigger_info.livetime:
                raise ValueError(
                    f"Period between frames (exposure time - deadtime) "
                    f"{period_between_frames} cannot be lower than exposure time of "
                    f"{trigger_info.livetime}"
                )

            coros.extend(
                [
                    self._driver.exposure_time.set(trigger_info.livetime),
                    self._driver.period_between_frames.set(period_between_frames),
                ]
            )
        if not isinstance(trigger_info.number_of_events, int):
            raise ValueError("Number of events must be an integer")

        await self._driver.frames_per_acq.set(trigger_info.number_of_events)
        coros.extend(
            [
                self._driver.trigger_mode.set(
                    JUNGFRAU_TRIGGER_MODE_MAP[trigger_info.trigger]
                ),
                self._driver.frames_per_acq.set(trigger_info.number_of_events),
            ]
        )
        await asyncio.gather(*coros)

    async def arm(self):
        await self._driver.acquisition_start.trigger()

    async def wait_for_idle(self):
        await wait_for_value(
            self._driver.detector_status, DetectorStatus.IDLE, timeout=DEFAULT_TIMEOUT
        )

    async def disarm(self):
        await self._driver.acquisition_stop.trigger()
