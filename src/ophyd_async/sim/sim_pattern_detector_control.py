import asyncio
from typing import Optional

from ophyd_async.core import PathProvider
from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.detector import DetectorControl, DetectorTrigger
from ophyd_async.sim.pattern_generator import PatternGenerator


class SimPatternDetectorControl(DetectorControl):
    def __init__(
        self,
        pattern_generator: PatternGenerator,
        path_provider: PathProvider,
        exposure: float = 0.1,
    ) -> None:
        self.pattern_generator: PatternGenerator = pattern_generator
        self.pattern_generator.set_exposure(exposure)
        self.path_provider: PathProvider = path_provider
        self.task: Optional[asyncio.Task] = None
        super().__init__()

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = 0.01,
    ) -> AsyncStatus:
        assert exposure is not None
        period: float = exposure + self.get_deadtime(exposure)
        task = asyncio.create_task(
            self._coroutine_for_image_writing(exposure, period, num)
        )
        self.task = task
        return AsyncStatus(task)

    async def disarm(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    def get_deadtime(self, exposure: float) -> float:
        return 0.001

    async def _coroutine_for_image_writing(
        self, exposure: float, period: float, frames_number: int
    ):
        for _ in range(frames_number):
            self.pattern_generator.set_exposure(exposure)
            await asyncio.sleep(period)
            await self.pattern_generator.write_image_to_file()
