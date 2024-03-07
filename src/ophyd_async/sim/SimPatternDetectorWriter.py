from typing import Any, AsyncGenerator, AsyncIterator, Coroutine, Dict

from ophyd_async.core import DirectoryProvider

from bluesky.protocols import Descriptor

from ophyd_async.core.detector import DetectorWriter
from ophyd_async.sim.PatternGenerator import PatternGenerator


class SimPatternDetectorWriter(DetectorWriter):
    patternGenerator: PatternGenerator
    indices_written: int
    directory_provider:DirectoryProvider

    def __init__(
        self, patternGenerator: PatternGenerator, directoryProvider: DirectoryProvider
    ) -> None:
        self.patternGenerator = patternGenerator
        self.indices_written = 0
        self.directory_provider = directoryProvider

    def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        self.patternGenerator.open_file(self.directory_provider)
        pass

    def close(self) -> None:
        pass

    def collect_stream_docs(self, indices_written: int) -> AsyncIterator:
        self.patternGenerator.open_file()
        pass

    def observe_indices_written(self, timeout=...) -> AsyncGenerator[int, None]:
        pass

    def get_indices_written(self) -> int:
        return self.indices_written
