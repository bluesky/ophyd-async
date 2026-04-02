import asyncio
from dataclasses import dataclass

from ophyd_async.core import DetectorTriggerLogic, SignalDict

from ._io import XspressDetectorIO, XspressTriggerMode


async def _prepare_detector(
    detector: XspressDetectorIO,
    trigger_mode: XspressTriggerMode,
    num: int,
    livetime: float = 0.0,
):
    coros = [
        detector.trigger_mode.set(trigger_mode),
        detector.num_images.set(num),
    ]
    if livetime:
        coros += [
            detector.exposure_time.set(livetime),
        ]
    await asyncio.gather(*coros)


@dataclass
class XspressTriggerLogic(DetectorTriggerLogic):
    detector: XspressDetectorIO

    def get_deadtime(self, config_values: SignalDict) -> float:
        return 0.0001

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await _prepare_detector(self.detector, XspressTriggerMode.BURST, num, livetime)

    async def prepare_edge(self, num: int, livetime: float):
        await _prepare_detector(
            self.detector, XspressTriggerMode.HARDWARE, num, livetime
        )
