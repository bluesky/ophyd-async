from typing import Any, AsyncGenerator, AsyncIterator, Coroutine, Dict


from ophyd_async.core.detector import DetectorWriter
from ophyd_async.sim.PatternGenerator import PatternGenerator


class SimPatternDetectorWriter(DetectorWriter):
    patternGenerator: PatternGenerator

    def __init__(self, patternGenerator: PatternGenerator) -> None:
        self.patternGenerator = patternGenerator

        super().__init__()

    def open(self, multiplier: int = 1) -> Coroutine[Any, Any, Dict[str, DataKey]]:
        return super().open(multiplier)

    def close(self) -> Coroutine[Any, Any, None]:
        return super().close()

    def collect_stream_docs(self, indices_written: int) -> AsyncIterator:
        return super().collect_stream_docs(indices_written)

    def observe_indices_written(self, timeout=...) -> AsyncGenerator[int, None]:
        return super().observe_indices_written(timeout)

    def get_indices_written(self) -> Coroutine[Any, Any, int]:
        return super().get_indices_written()
