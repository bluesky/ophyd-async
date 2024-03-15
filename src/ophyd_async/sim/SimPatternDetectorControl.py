import asyncio
from typing import Optional

from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.detector import DetectorControl, DetectorTrigger
from ophyd_async.sim.SimDriver import SimDriver
from ophyd_async.core import DirectoryProvider


class SimPatternDetectorControl(DetectorControl):
    def __init__(
        self,
        pattern_generator: SimDriver,
        directory_provider: DirectoryProvider,
        exposure: float = 0.1,
    ) -> None:
        self.pattern_generator: SimDriver = pattern_generator
        self.pattern_generator.set_exposure(exposure)
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
        await self.pattern_generator.open_file(self.directory_provider)
        task = asyncio.create_task(self.image_writing_task(exposure, period, num))
        self.task = task
        return AsyncStatus(task)

    async def image_writing_task(
        self, exposure: float, period: float, frames_number: int
    ):
        """that is a coroutine that writes images to file

        Args:
            exposure (float): _description_
            period (float): _description_
            frames_number (int): _description_
        """
        async for i in range(frames_number):
            self.pattern_generator.set_exposure(exposure)
            await asyncio.sleep(period)
            self.pattern_generator.write_image_to_file()

    async def get_deadtime(self, exposure: float) -> float:
        return 0.001

    async def disarm(self):
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        self.task = None
