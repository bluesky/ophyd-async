from typing import AsyncGenerator, AsyncIterator, Dict, List

from bluesky.protocols import Descriptor

from ophyd_async.core import DirectoryProvider
from ophyd_async.core.detector import DetectorWriter
from ophyd_async.core.signal import observe_value
from ophyd_async.sim.SimDriver import SimDriver


class SimPatternDetectorWriter(DetectorWriter):
    patternGenerator: SimDriver

    def __init__(
        self, patternGenerator: SimDriver, directoryProvider: DirectoryProvider
    ) -> None:
        self.patternGenerator = patternGenerator
        self.directory_provider = directoryProvider

    def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        self.patternGenerator.open_file(self.directory_provider)
        outer_shape = (multiplier,) if multiplier > 1 else ()
        describe = {
            ds.name: Descriptor(
                source=f"sim://{ds.name}",
                shape=outer_shape + tuple(ds.shape),
                dtype="array" if ds.shape != [1] else "number",
                external="STREAM:",
            )
            for ds in self.patternGenerator._datasets
        }
        return describe

    def close(self) -> None:
        self.patternGenerator.handle_for_h5_file.close()

    def collect_stream_docs(self, indices_written: int) -> AsyncIterator:
        # todo fillout 
        self.patternGenerator.handle_for_h5_file.flush()
        if self.patternGenerator.indices_written:
            if not self.patternGenerator.file:
                self._filestream_
                self.patternGenerator.file = _HDFFile(
                    self.directory_provider,
                    self.patternGenerator.handle_for_h5_file,
                    self.patternGenerator._datasets,
                )
                for doc in self.patternGenerator.file.stream_resources():
                    yield "stream_resource", doc
        # self.patternGenerator.open_file()
        # for doc in self.patternGenerator.file.stream

    async def observe_indices_written(self, timeout=...) -> AsyncGenerator[int, None]:
        async for num_captured in observe_value(
            self.patternGenerator.written_images_counter, timeout=timeout
        ):
            yield num_captured // self.patternGenerator.multiplier

    def get_indices_written(self) -> int:
        return self.patternGenerator.written_images_counter
