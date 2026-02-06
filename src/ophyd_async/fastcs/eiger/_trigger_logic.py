import asyncio

from ophyd_async.core import DetectorTriggerLogic, SignalDict

from ._io import EigerDetectorIO, EigerTriggerMode


async def _prepare_detector(
    detector: EigerDetectorIO,
    trigger_mode: EigerTriggerMode,
    num: int,
    livetime: float = 0.0,
):
    coros = [
        detector.trigger_mode.set(trigger_mode),
        detector.nimages.set(num),
    ]
    if livetime:
        coros += [
            detector.count_time.set(livetime),
            detector.frame_time.set(livetime),
        ]
    await asyncio.gather(*coros)


class EigerTriggerLogic(DetectorTriggerLogic):
    def __init__(
        self,
        detector: EigerDetectorIO,
    ) -> None:
        self.detector = detector

    def get_deadtime(self, config_values: SignalDict) -> float:
        # See https://media.dectris.com/filer_public/30/14/3014704e-5f3b-43ba-8ccf-8ef720e60d2a/240202_usermanual_eiger2.pdf
        return 0.0001

    async def prepare_internal(self, num: int, livetime: float, deadtime: float):
        await _prepare_detector(self.detector, EigerTriggerMode.INTERNAL, num, livetime)

    async def prepare_edge(self, num: int, livetime: float):
        await _prepare_detector(self.detector, EigerTriggerMode.EDGE, num, livetime)

    async def prepare_level(self, num: int):
        await _prepare_detector(self.detector, EigerTriggerMode.GATE, num)
