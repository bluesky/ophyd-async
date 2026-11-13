from ophyd_async.core import DEFAULT_TIMEOUT, DetectorAcquireLogic, wait_for_value

from ._io import XspressDetectorIO


class XspressAcquireLogic(DetectorAcquireLogic):
    def __init__(self, detector: XspressDetectorIO) -> None:
        self.detector = detector

    async def start_acquiring(self):
        await self.detector.start_acquisition.trigger()

    async def wait_for_idle(self):
        await wait_for_value(
            self.detector.acquisition_complete, True, timeout=DEFAULT_TIMEOUT
        )

    async def ensure_stopped(self):
        await self.detector.stop_acquisition.trigger()
