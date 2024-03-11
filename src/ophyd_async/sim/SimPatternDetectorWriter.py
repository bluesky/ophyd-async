from typing import AsyncGenerator, AsyncIterator, Dict

from bluesky.protocols import Descriptor

from ophyd_async.core import DirectoryProvider
from ophyd_async.core.detector import DetectorWriter
from ophyd_async.core.signal import observe_value
from ophyd_async.sim.PatternGenerator import PatternGenerator


class SimPatternDetectorWriter(DetectorWriter):
    patternGenerator: PatternGenerator

    def __init__(
        self, patternGenerator: PatternGenerator, directoryProvider: DirectoryProvider
    ) -> None:
        self.patternGenerator = patternGenerator
        self.directory_provider = directoryProvider

    def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        self.patternGenerator.open_file(self.directory_provider)
        # todo replicate description-generating logic from HDFWriter

    def close(self) -> None:
        self.patternGenerator.file.close()

    def collect_stream_docs(self, indices_written: int) -> AsyncIterator:
        # self.patternGenerator.open_file()
        # for doc in self.patternGenerator.file.stream
        pass

    async def observe_indices_written(self, timeout=...) -> AsyncGenerator[int, None]:
        async for num_captured in observe_value(
            self.patternGenerator.written_images_counter, timeout=timeout
        ):
            yield num_captured // self.patternGenerator.multiplier

    def get_indices_written(self) -> int:
        return self.patternGenerator.written_images_counter
