from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorArmLogic,
    SignalX,
    wait_for_value,
)

from ._io import EigerDetectorIO


class EigerArmLogic(DetectorArmLogic):
    def __init__(self, detector: EigerDetectorIO, arm_when_ready: SignalX) -> None:
        self.detector = detector
        self.arm_when_ready = arm_when_ready

    async def arm(self):
        await self.arm_when_ready.trigger()

    async def wait_for_idle(self):
        await wait_for_value(self.detector.state, "idle", timeout=DEFAULT_TIMEOUT)

    async def disarm(self, on_unstage: bool):
        await self.detector.disarm.trigger()
