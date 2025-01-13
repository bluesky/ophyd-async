import asyncio
import time
from contextlib import suppress

from ophyd_async.core import DetectorController
from ophyd_async.core._detector import TriggerInfo

from ._pattern_generator import PatternGenerator


class BlobDetectorController(DetectorController):
    def __init__(self, pattern_generator: PatternGenerator):
        self.pattern_generator = pattern_generator
        self.trigger_info: TriggerInfo | None = None
        self.task: asyncio.Task | None = None

    def get_deadtime(self, exposure):
        return 0.001

    async def prepare(self, trigger_info):
        # Just hold onto the trigger info until we need it
        self.trigger_info = trigger_info

    async def _write_images(
        self, exposure: float, period: float, number_of_frames: int
    ):
        start = time.monotonic()
        for i in range(1, number_of_frames + 1):
            deadline = start + i * period
            timeout = deadline - time.monotonic()
            await asyncio.sleep(timeout)
            self.pattern_generator.write_image_to_file(exposure)

    async def arm(self):
        if self.trigger_info is None:
            raise RuntimeError(f"prepare() not called on {self}")
        livetime = self.trigger_info.livetime or 0.1
        coro = self._write_images(
            exposure=livetime,
            period=livetime + self.trigger_info.deadtime,
            number_of_frames=self.trigger_info.total_number_of_triggers,
        )
        self.task = asyncio.create_task(coro)

    async def wait_for_idle(self):
        if self.task:
            await self.task

    async def disarm(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
