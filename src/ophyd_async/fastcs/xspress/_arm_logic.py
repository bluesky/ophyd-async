from ophyd_async.core import DEFAULT_TIMEOUT, DetectorArmLogic, wait_for_value

from ._io import XspressDetectorIO


class XspressArmLogic(DetectorArmLogic):
    def __init__(self, detector: XspressDetectorIO) -> None:
        self.detector = detector

    async def arm(self):
        await self.detector.start_acquisition.trigger()

    async def wait_for_idle(self):
        await wait_for_value(
            self.detector.acquisition_complete, True, timeout=DEFAULT_TIMEOUT
        )

    async def disarm(self, on_unstage: bool):
        await self.detector.stop_acquisition.trigger()
