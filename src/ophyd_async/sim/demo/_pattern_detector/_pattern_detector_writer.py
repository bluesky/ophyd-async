from collections.abc import AsyncGenerator, AsyncIterator

from event_model import DataKey

from ophyd_async.core import DEFAULT_TIMEOUT, DetectorWriter, NameProvider, PathProvider

from ._pattern_generator import PatternGenerator


class PatternDetectorWriter(DetectorWriter):
    pattern_generator: PatternGenerator

    def __init__(
        self,
        pattern_generator: PatternGenerator,
        path_provider: PathProvider,
        name_provider: NameProvider,
    ) -> None:
        self.pattern_generator = pattern_generator
        self.path_provider = path_provider
        self.name_provider = name_provider

    async def open(self, multiplier: int = 1) -> dict[str, DataKey]:
        return await self.pattern_generator.open_file(
            self.path_provider, self.name_provider(), multiplier
        )

    async def close(self) -> None:
        self.pattern_generator.close()

    def collect_stream_docs(self, indices_written: int) -> AsyncIterator:
        return self.pattern_generator.collect_stream_docs(indices_written)

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        async for index in self.pattern_generator.observe_indices_written(timeout):
            yield index

    async def get_indices_written(self) -> int:
        return self.pattern_generator.image_counter
