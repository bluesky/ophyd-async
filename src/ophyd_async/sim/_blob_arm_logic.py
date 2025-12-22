import asyncio
from contextlib import suppress

from ophyd_async.core import DetectorArmLogic, TriggerInfo

from ._pattern_generator import PatternGenerator


class BlobArmLogic(DetectorArmLogic):
    def __init__(self, pattern_generator: PatternGenerator):
        self.pattern_generator = pattern_generator
        self.trigger_info: TriggerInfo | None = None
        self.task: asyncio.Task | None = None

    async def arm(self):
        # Start a background process off writing the images to file
        self.task = asyncio.create_task(self.pattern_generator.write_images_to_file())

    async def wait_for_idle(self):
        # Wait for the background task to complete
        if self.task:
            await self.task

    async def disarm(self):
        # Stop the background task and wait for it to finish
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
