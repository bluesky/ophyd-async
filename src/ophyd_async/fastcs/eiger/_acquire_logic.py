from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorAcquireLogic,
    TriggerableCommand,
    wait_for_value,
)

from ._io import EigerDetectorIO


class EigerAcquireLogic(DetectorAcquireLogic):
    def __init__(
        self, detector: EigerDetectorIO, arm_when_ready: TriggerableCommand
    ) -> None:
        self.detector = detector
        self.arm_when_ready = arm_when_ready

    async def start_acquiring(self):
        await self.arm_when_ready.trigger()

    async def wait_for_idle(self):
        await wait_for_value(self.detector.state, "idle", timeout=DEFAULT_TIMEOUT)

    async def ensure_stopped(self):
        await self.detector.disarm.trigger()
