import asyncio

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorController,
    DetectorTrigger,
    TriggerInfo,
    wait_for_value,
)
from ophyd_async.fastcs.jungfrau import (
    JUNGFRAU_TRIGGER_MODE_MAP,
    DetectorStatus,
    JungfrauDriverIO,
)

# TODO other assertions: external trigger mode: module must be triggered with signal at
# least 100ns long
# Exposure time > 2us
# exposure timeout > 25ns
# exposure period, don't exceed 100 per second
# exposure time must be compatible with exposure period

# Autotrigger mode:
# trigger mode: auto
# No. triggers: 1
# No frames: Any
# Exposure period: < 100

# Internal trigger:
# trigger mode: trigger
# extsig0: in-rising-edge
# no. triggers: any
# No. frames = acqs per trigger, normally 1.
# Exposure period: doesn't matter if above is 1

# TODO create a util plan for create trigger_info_for_autotriggering and
# # create_trigger_info_for_internal_triggering


class JungfrauController(DetectorController):
    def __init__(self, driver: JungfrauDriverIO):
        self._driver = driver

    def get_deadtime(self, exposure: float | None) -> float:
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

        coros = []
        if trigger_info.trigger == DetectorTrigger.INTERNAL:
            if not TriggerInfo.livetime:
                raise ValueError(
                    "Must set TriggerInfo.Livetime for internal trigger mode"
                )
            coros.extend(
                [
                    self._driver.exposure_time.set(TriggerInfo.livetime),
                    self._driver.period_between_frames.set(
                        TriggerInfo.livetime - TriggerInfo.deadtime
                    ),
                ]
            )
        if not isinstance(TriggerInfo.number_of_events, int):
            raise ValueError("Number of events must be an integer")

        await self._driver.frames_per_acq.set(TriggerInfo.number_of_events)
        coros.extend(
            [
                self._driver.trigger_mode.set(
                    JUNGFRAU_TRIGGER_MODE_MAP[trigger_info.trigger]
                ),
                self._driver.frames_per_acq.set(TriggerInfo.number_of_events),
            ]
        )
        # todo test if ordering of these signals matters.
        await asyncio.gather(*coros)

    async def arm(self):
        await self._driver.start.trigger()

    # TODO double check sensible timeout
    async def wait_for_idle(self):
        await wait_for_value(
            self._driver.detector_status, DetectorStatus.IDLE, timeout=DEFAULT_TIMEOUT
        )

    async def disarm(self):
        await self._driver.acquisition_stop.trigger()
