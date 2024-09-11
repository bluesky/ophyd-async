import asyncio
from typing import Optional

from pydantic import Field

from ophyd_async.core import AsyncStatus, DetectorControl, PathProvider
from ophyd_async.core._detector import TriggerInfo

from ._pattern_generator import PatternGenerator


class PatternDetectorController(DetectorControl):
    def __init__(
        self,
        pattern_generator: PatternGenerator,
        path_provider: PathProvider,
        exposure: float = Field(default=0.1),
    ) -> None:
        self.pattern_generator: PatternGenerator = pattern_generator
        self.pattern_generator.set_exposure(exposure)
        self.path_provider: PathProvider = path_provider
        self.task: Optional[asyncio.Task] = None
        super().__init__()

    async def prepare(
        self, trigger_info: TriggerInfo = TriggerInfo(number=1, livetime=0.01)
    ):
        if trigger_info.livetime is None:
            trigger_info.livetime = 0.01
        period: float = trigger_info.livetime + self.get_deadtime(trigger_info.livetime)
        self.task = asyncio.create_task(
            self._coroutine_for_image_writing(
                trigger_info.livetime, period, trigger_info.number
            )
        )

    async def arm(self) -> AsyncStatus:
        assert self.task
        return AsyncStatus(self.task)

    async def disarm(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    def get_deadtime(self, exposure: float | None) -> float:
        return 0.001

    async def _coroutine_for_image_writing(
        self, exposure: float, period: float, frames_number: int
    ):
        for _ in range(frames_number):
            self.pattern_generator.set_exposure(exposure)
            await asyncio.sleep(period)
            await self.pattern_generator.write_image_to_file()
