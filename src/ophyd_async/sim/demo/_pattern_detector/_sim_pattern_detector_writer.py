from typing import AsyncGenerator, AsyncIterator, Dict

from bluesky.protocols import DataKey

from ophyd_async.core import DetectorWriter, DirectoryProvider

from ._pattern_generator import PatternGenerator


class SimPatternDetectorWriter(DetectorWriter):
    pattern_generator: PatternGenerator

    def __init__(
        self, pattern_generator: PatternGenerator, directoryProvider: DirectoryProvider
    ) -> None:
        self.pattern_generator = pattern_generator
        self.directory_provider = directoryProvider

    async def open(self, multiplier: int = 1) -> Dict[str, DataKey]:
        return await self.pattern_generator.open_file(
            self.directory_provider, multiplier
        )

    async def close(self) -> None:
        self.pattern_generator.close()

    def collect_stream_docs(self, indices_written: int) -> AsyncIterator:
        return self.pattern_generator.collect_stream_docs(indices_written)

    def observe_indices_written(self, timeout=...) -> AsyncGenerator[int, None]:
        return self.pattern_generator.observe_indices_written()

    async def get_indices_written(self) -> int:
        return self.pattern_generator.written_images_counter
