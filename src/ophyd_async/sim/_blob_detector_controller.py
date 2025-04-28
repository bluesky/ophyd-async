import asyncio
from contextlib import suppress

from ophyd_async.core import DetectorController, DetectorTrigger, TriggerInfo

from ._pattern_generator import PatternGenerator


class BlobDetectorController(DetectorController):
    def __init__(self, pattern_generator: PatternGenerator):
        self.pattern_generator = pattern_generator
        self.trigger_info: TriggerInfo | None = None
        self.task: asyncio.Task | None = None

    def get_deadtime(self, exposure):
        return 0.001

    async def prepare(self, trigger_info: TriggerInfo):
        # This is a simulation, so only support intenal triggering
        if trigger_info.trigger != DetectorTrigger.INTERNAL:
            raise RuntimeError(f"{trigger_info.trigger} not supported by {self}")
        # Just hold onto the trigger info until we need it
        self.trigger_info = trigger_info

    async def arm(self):
        if self.trigger_info is None:
            raise RuntimeError(f"prepare() not called on {self}")
        livetime = self.trigger_info.livetime or 0.1
        # Start a background process off writing the images to file
        coro = self.pattern_generator.write_images_to_file(
            exposure=livetime,
            period=livetime + self.trigger_info.deadtime,
            number_of_frames=self.trigger_info.total_number_of_exposures,
        )
        self.task = asyncio.create_task(coro)

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
