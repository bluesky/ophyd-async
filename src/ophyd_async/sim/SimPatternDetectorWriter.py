from typing import Any, AsyncGenerator, AsyncIterator, Coroutine, Dict


from bluesky.protocols import Descriptor

from ophyd_async.core.detector import DetectorWriter
from ophyd_async.sim.PatternGenerator import PatternGenerator


class SimPatternDetectorWriter(DetectorWriter):
    patternGenerator: PatternGenerator
    indices_written: int

    def __init__(self, patternGenerator: PatternGenerator) -> None:
        self.patternGenerator = patternGenerator
        self.indices_written = 0

    def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        pass

    def close(self) -> Coroutine[Any, Any, None]:
        pass

    def collect_stream_docs(self, indices_written: int) -> AsyncIterator:
        pass

    def observe_indices_written(self, timeout=...) -> AsyncGenerator[int, None]:
        pass

    def get_indices_written(self) -> int:
        return self.indices_written
