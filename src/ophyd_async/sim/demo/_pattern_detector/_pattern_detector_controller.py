import asyncio

from ophyd_async.core import DetectorController, PathProvider
from ophyd_async.core._detector import TriggerInfo

from ._pattern_generator import PatternGenerator


class PatternDetectorController(DetectorController):
    def __init__(
        self,
        pattern_generator: PatternGenerator,
        path_provider: PathProvider,
        exposure: float = 0.1,
    ) -> None:
        self.pattern_generator: PatternGenerator = pattern_generator
        self.pattern_generator.set_exposure(exposure)
        self.path_provider: PathProvider = path_provider
        self.task: asyncio.Task | None = None
        super().__init__()

    async def prepare(self, trigger_info: TriggerInfo):
        self._trigger_info = trigger_info
        if self._trigger_info.livetime is None:
            self._trigger_info.livetime = 0.01
        self.period: float = self._trigger_info.livetime + self.get_deadtime(
            trigger_info.livetime
        )

    async def arm(self):
        assert self._trigger_info.livetime
        assert self.period
        self.task = asyncio.create_task(
            self._coroutine_for_image_writing(
                self._trigger_info.livetime,
                self.period,
                self._trigger_info.total_number_of_triggers,
            )
        )

    async def wait_for_idle(self):
        if self.task:
            await self.task

    async def disarm(self):
        if self.task and not self.task.done():
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
