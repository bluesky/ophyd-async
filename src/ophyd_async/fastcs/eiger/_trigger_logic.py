import asyncio
from dataclasses import dataclass

from ophyd_async.core import DetectorTriggerLogic, SignalDict

from ._io import EigerDetectorIO, EigerTriggerMode

# Conservative readout time for the detector
# TODO: Investigate range of possible value for
# detector_readout_time, and implement get_deadtime correctly
_MIN_DEADTIME = 0.0001


async def _prepare_detector(
    detector: EigerDetectorIO,
    trigger_mode: EigerTriggerMode,
    num_images: int,
    num_triggers: int,
    livetime: float = 0.0,
    deadtime: float = _MIN_DEADTIME,
):
    coros = [
        detector.trigger_mode.set(trigger_mode),
        detector.nimages.set(num_images),
        detector.ntrigger.set(num_triggers),
    ]
    if livetime:
        coros += [
            detector.count_time.set(livetime),
            detector.frame_time.set(livetime + deadtime),
        ]
    await asyncio.gather(*coros)


@dataclass
class EigerTriggerLogic(DetectorTriggerLogic):
    detector: EigerDetectorIO

    def get_deadtime(self, config_values: SignalDict) -> float:
        return _MIN_DEADTIME

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        # frame_time - count_time < readout makes the detector shorten count_time
        deadtime = max(_MIN_DEADTIME, deadtime)
        await _prepare_detector(
            self.detector, EigerTriggerMode.INTERNAL, num, 1, livetime, deadtime
        )

    async def prepare_edge(self, num: int, livetime: float):
        # One image per edge, frame_time only needs to leave room for readout
        await _prepare_detector(self.detector, EigerTriggerMode.EDGE, 1, num, livetime)

    async def prepare_level(self, num: int):
        # Exposure is timed by the gate signal, so count/frame_time are not set
        await _prepare_detector(self.detector, EigerTriggerMode.GATE, 1, num)
