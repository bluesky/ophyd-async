from ophyd_async.core import DEFAULT_TIMEOUT, DetectorArmLogic, wait_for_value

from ._io import EigerDetectorIO


class EigerArmLogic(DetectorArmLogic):
    def __init__(self, detector: EigerDetectorIO) -> None:
        self.detector = detector

    async def arm(self):
        await self.detector.arm.trigger()

    async def wait_for_idle(self):
        await wait_for_value(self.detector.state, "idle", timeout=DEFAULT_TIMEOUT)

    async def disarm(self):
        await self.detector.disarm.trigger()
