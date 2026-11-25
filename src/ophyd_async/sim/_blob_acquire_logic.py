import asyncio

from ophyd_async.core import DetectorAcquireLogic, TriggerInfo, cancel_and_wait

from ._pattern_generator import PatternGenerator


class BlobAcquireLogic(DetectorAcquireLogic):
    def __init__(self, pattern_generator: PatternGenerator):
        self.pattern_generator = pattern_generator
        self.trigger_info: TriggerInfo | None = None
        self.task: asyncio.Task | None = None

    async def start_acquiring(self):
        # Start a background process off writing the images to file
        self.task = asyncio.create_task(self.pattern_generator.write_images_to_file())

    async def wait_for_idle(self):
        # Wait for the background task to complete
        if self.task:
            await self.task

    async def ensure_stopped(self):
        # Stop the background task and wait for it to finish
        if self.task:
            task, self.task = self.task, None
            await cancel_and_wait(task)
