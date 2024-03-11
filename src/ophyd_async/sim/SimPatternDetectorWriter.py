from typing import AsyncGenerator, AsyncIterator, Dict

from bluesky.protocols import Descriptor

from ophyd_async.core import DirectoryProvider
from ophyd_async.core.detector import DetectorWriter
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

    def close(self) -> None:
        self.patternGenerator.file.close()

    def collect_stream_docs(self, indices_written: int) -> AsyncIterator:
        self.patternGenerator.open_file()

    def observe_indices_written(self, timeout=...) -> AsyncGenerator[int, None]:
        pass

    def get_indices_written(self) -> int:
        return self.patternGenerator.indices_written
