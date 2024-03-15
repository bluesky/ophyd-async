import asyncio
from typing import Optional

from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.detector import DetectorControl, DetectorTrigger
from ophyd_async.sim.SimDriver import SimDriver
from ophyd_async.core import DirectoryProvider


class SimPatternDetectorControl(DetectorControl):
    def __init__(
        self,
        driver: SimDriver,
        directory_provider: DirectoryProvider,
        exposure: float = 0.1,
    ) -> None:
        self.driver: SimDriver = driver
        self.driver.set_exposure(exposure)
        self.directory_provider: DirectoryProvider = directory_provider
        self.task: Optional[asyncio.Task] = None
        super().__init__()

    async def arm(
        self,
        num: int,
        trigger: DetectorTrigger = DetectorTrigger.internal,
        exposure: Optional[float] = 0.01,
    ) -> AsyncStatus:
        period: float = exposure + await self.get_deadtime(exposure)
        await self.driver.open_file(self.directory_provider)
        task = asyncio.create_task(
            self._coroutine_for_image_writing(exposure, period, num)
        )
        self.task = task
        return AsyncStatus(task)

    async def disarm(self):
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        self.task = None

    async def get_deadtime(self, exposure: float) -> float:
        return 0.001

    async def _coroutine_for_image_writing(
        self, exposure: float, period: float, frames_number: int
    ):
        async for i in range(frames_number):
            self.driver.set_exposure(exposure)
            await asyncio.sleep(period)
            self.driver.write_image_to_file()
