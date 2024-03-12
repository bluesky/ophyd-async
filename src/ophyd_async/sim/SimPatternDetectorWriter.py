from typing import AsyncGenerator, AsyncIterator, Dict, List

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
        outer_shape = (multiplier,) if multiplier > 1 else ()
        return {
            "test": {
                "source": "sim://HDF:FullFileName_RBV",
                "shape": (10, 10),
                "dtype": "array",
                "external": "STREAM:",
            },
            "test2": {
                "source": "sim://HDF:FullFileName_NULL",
                "shape:": (10, 10),
                "dtype": "array",
                "external": "STREAM",
            },
        }
        describe = {
            str(i): Descriptor(
                source=self.hdf.full_file_name.source,  # todo not sure which abstraction to use?
                # todo see how many 'interesting image' frames are done in the generator
                shape=outer_shape + tuple(1, 1),
                dtype="array",  # if ds.shape else "number",
                external="STREAM:",
            )
            for i in range(0, 10)  # todo where to get datasets from?
            # for index, name in enumerate(self._datasets)
        }
        return describe

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
