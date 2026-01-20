import asyncio
import logging

from ophyd_async.core import DetectorTriggerLogic, SignalDict, SignalRW

from ._io import AcquisitionType, JungfrauDriverIO, JungfrauTriggerMode, PedestalMode

# Deadtime is dependant on a wide combination of settings and on trigger mode
# but this is safe upper-limit
JUNGFRAU_DEADTIME_S = 2e-5

logger = logging.getLogger("ophyd_async")


async def get_and_reset_acquisition_type(
    acquisition_type: SignalRW[AcquisitionType],
) -> AcquisitionType:
    acquisition_type_value = await acquisition_type.get_value()
    # Pedestal mode is one-shot, so set back the request value
    await acquisition_type.set(AcquisitionType.STANDARD)
    logger.info(f"Preparing Jungfrau in {acquisition_type_value} mode.")
    return acquisition_type_value


async def prepare_exposures(
    detector: JungfrauDriverIO, livetime: float, deadtime: float = 0
):
    # ValueErrors and warnings in this function come from the jungfrau operation
    # docs: https://rtd.xfel.eu/docs/jungfrau-detector-documentation/en/latest/operation.html
    if not livetime:
        livetime = await detector.exposure_time.get_value()
    if livetime < 2e-6:
        logger.warning("Exposure time shorter than 2μs is not recommended")
    if not deadtime:
        deadtime = JUNGFRAU_DEADTIME_S
    period_between_frames = livetime + deadtime
    if period_between_frames < JUNGFRAU_DEADTIME_S:
        raise ValueError(
            f"Period between frames (exposure time + deadtime) = "
            f"{period_between_frames}s cannot be lower than minimum detector "
            f"deadtime {JUNGFRAU_DEADTIME_S}"
        )
    await asyncio.gather(
        detector.period_between_frames.set(period_between_frames),
        detector.exposure_time.set(livetime),
    )


async def prepare_standard_mode(
    detector: JungfrauDriverIO,
    trigger_mode: JungfrauTriggerMode,
    num: int,
    livetime: float,
    deadtime: float = 0,
) -> None:
    await asyncio.gather(
        detector.trigger_mode.set(trigger_mode),
        prepare_exposures(detector, livetime, deadtime),
        detector.frames_per_acq.set(num),
    )


async def prepare_pedestal_mode(
    detector: JungfrauDriverIO, num: int, livetime: float, deadtime: float
):
    frames, loops = await asyncio.gather(
        detector.pedestal_mode_frames.get_value(),
        detector.pedestal_mode_loops.get_value(),
    )
    if 2 * frames * loops != num:
        # No. events is double the pedestal loops,
        # since pedestal scan does the entire loop
        # twice.
        raise ValueError(
            f"Invalid trigger info for pedestal mode. "
            f"{num} must be equal to 2 * {frames} * {loops}. "
            f"Was create_jungfrau_pedestal_triggering_info used?"
        )
    await prepare_exposures(detector, livetime, deadtime)
    # Setting signals once the detector is in pedestal mode can cause errors,
    # so do this last
    await detector.pedestal_mode_state.set(PedestalMode.ON)


class JungfrauTriggerLogic(DetectorTriggerLogic):
    def __init__(
        self, detector: JungfrauDriverIO, acquisition_type: SignalRW[AcquisitionType]
    ):
        self.detector = detector
        self.acquisition_type = acquisition_type

    # Deadtime here is really used as "time between frames"
    def get_deadtime(self, config_values: SignalDict) -> float:
        return JUNGFRAU_DEADTIME_S

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        acquisition_type = await get_and_reset_acquisition_type(self.acquisition_type)
        if acquisition_type == AcquisitionType.PEDESTAL:
            await prepare_pedestal_mode(self.detector, num, livetime, deadtime)
        else:
            await prepare_standard_mode(
                self.detector, JungfrauTriggerMode.INTERNAL, num, livetime, deadtime
            )

    async def prepare_edge(self, num: int, livetime: float):
        acquisition_type = await get_and_reset_acquisition_type(self.acquisition_type)
        if acquisition_type == AcquisitionType.PEDESTAL:
            raise ValueError(
                "Jungfrau must be triggered internally while in pedestal mode."
            )
        else:
            await prepare_standard_mode(
                self.detector, JungfrauTriggerMode.EXTERNAL, num, livetime
            )
