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
    AcquisitionType,
    DetectorStatus,
    JungfrauDriverIO,
    PedestalMode,
)

# Deadtime is dependant on a wide combination of settings and on trigger mode
# but this is safe upper-limit
JUNGFRAU_DEADTIME_S = 2e-5

logger = logging.getLogger("ophyd_async")


class JungfrauController(DetectorController):
    def __init__(self, driver: JungfrauDriverIO):
        self._driver = driver

    def get_deadtime(self, exposure: float | None = None) -> float:
        return JUNGFRAU_DEADTIME_S

    async def prepare(self, trigger_info: TriggerInfo) -> None:
        # ValueErrors and warnings in this function come from the jungfrau operation
        # docs: https://rtd.xfel.eu/docs/jungfrau-detector-documentation/en/latest/operation.html

        # Deadtime here is really used as "time between frames"

        acquisition_type = await self._driver.acquisition_type.get_value()
        logger.info(f"Preparing Jungfrau in {acquisition_type} mode.")

        if trigger_info.trigger not in (
            DetectorTrigger.INTERNAL,
            DetectorTrigger.EDGE_TRIGGER,
        ):
            raise ValueError(
                "The trigger method can only be called with internal or edge triggering"
            )
        if (
            acquisition_type == AcquisitionType.PEDESTAL
            and trigger_info.trigger != DetectorTrigger.INTERNAL
        ):
            raise ValueError(
                "Jungfrau must be triggered internally while in pedestal mode."
            )

        if not isinstance(trigger_info.number_of_events, int):
            raise TypeError("Number of events must be an integer")

        if acquisition_type != AcquisitionType.PEDESTAL:
            if (
                trigger_info.trigger == DetectorTrigger.INTERNAL
                and trigger_info.number_of_events != 1
            ):
                raise ValueError(
                    "Number of events must be set to 1 in internal trigger mode during "
                    "standard acquisitions."
                )

            if (
                trigger_info.trigger == DetectorTrigger.EDGE_TRIGGER
                and trigger_info.exposures_per_event != 1
            ):
                raise ValueError(
                    "Exposures per event must be set to 1 in edge trigger mode "
                    "during standard acquisitions."
                )

        if not trigger_info.livetime:
            raise ValueError("Must set TriggerInfo.livetime")

        if trigger_info.livetime < 2e-6:
            logger.warning("Exposure time shorter than 2μs is not recommended")

        period_between_frames = trigger_info.livetime + trigger_info.deadtime

        if period_between_frames < self.get_deadtime():
            raise ValueError(
                f"Period between frames (exposure time - deadtime) = "
                f"{period_between_frames}s cannot be lower than minimum detector "
                f"deadtime {self.get_deadtime()}"
            )

        coros = [
            self._driver.trigger_mode.set(
                JUNGFRAU_TRIGGER_MODE_MAP[trigger_info.trigger]
            ),
            self._driver.period_between_frames.set(period_between_frames),
            self._driver.exposure_time.set(trigger_info.livetime),
        ]

        match acquisition_type:
            case AcquisitionType.STANDARD:
                frames_signal = (
                    trigger_info.exposures_per_event
                    if trigger_info.trigger is DetectorTrigger.INTERNAL
                    else trigger_info.number_of_events
                )
                coros.extend(
                    [
                        self._driver.frames_per_acq.set(frames_signal),
                    ]
                )
            case AcquisitionType.PEDESTAL:
                if trigger_info.number_of_events % 2 == 0:
                    coros.extend(
                        [
                            self._driver.pedestal_mode_frames.set(
                                trigger_info.exposures_per_event
                            ),
                            # No. events is double the pedestal loops,
                            # since pedestal scan does the entire loop
                            # twice.
                            self._driver.pedestal_mode_loops.set(
                                int(trigger_info.number_of_events / 2)
                            ),
                        ]
                    )
                else:
                    raise ValueError(
                        f"Invalid trigger info for pedestal mode. "
                        f"{trigger_info.number_of_events=} must be divisible by two. "
                        f"Was create_jungfrau_pedestal_triggering_info used?"
                    )

        await asyncio.gather(*coros)

        # Setting signals once the detector is in pedestal mode can cause errors,
        # so do this last
        if acquisition_type == AcquisitionType.PEDESTAL:
            await self._driver.pedestal_mode_state.set(PedestalMode.ON)

    async def arm(self):
        await self._driver.acquisition_start.trigger()

    async def wait_for_idle(self):
        await wait_for_value(
            self._driver.detector_status, DetectorStatus.IDLE, timeout=DEFAULT_TIMEOUT
        )

    async def disarm(self):
        await self._driver.acquisition_stop.trigger()
        await asyncio.gather(
            self._driver.pedestal_mode_state.set(PedestalMode.OFF),
            self._driver.acquisition_type.set(AcquisitionType.STANDARD),
        )
