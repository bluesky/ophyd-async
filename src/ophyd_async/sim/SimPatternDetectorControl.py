import asyncio
from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.detector import DetectorControl
from ophyd_async.sim.PatternGenerator import PatternGenerator


class SimPatternDetectorControl(DetectorControl):
    patternGenerator: PatternGenerator

    def __init__(
        self, patternGenerator: PatternGenerator, exposure: float = 0.1
    ) -> None:
        self.patternGenerator = patternGenerator
        self.patternGenerator.set_exposure(exposure)
        self.patternGenerator.open_file()
        super().__init__()

    async def arm(self) -> AsyncStatus:
        return asyncio.create_task(self.patternGenerator.open_file())
    
    async def get_deadtime(self, exposure: float) -> float:
        return super().get_deadtime(exposure)

    async def disarm(self):
        return await super().disarm
