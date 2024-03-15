from typing import AsyncGenerator, AsyncIterator, Dict

from bluesky.protocols import Descriptor

from ophyd_async.core import DirectoryProvider
from ophyd_async.core.detector import DetectorWriter
from ophyd_async.core.signal import observe_value
from ophyd_async.sim.SimDriver import SimDriver


class SimPatternDetectorWriter(DetectorWriter):
    driver: SimDriver

    def __init__(self, driver: SimDriver, directoryProvider: DirectoryProvider) -> None:
        self.driver = driver
        self.directory_provider = directoryProvider

    def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        self.driver.open_file(self.directory_provider, multiplier)

    def close(self) -> None:
        self.driver.close()

    def collect_stream_docs(self, indices_written: int) -> AsyncIterator:
        return self.driver.collect_stream_docs()

    async def observe_indices_written(self, timeout=...) -> AsyncGenerator[int, None]:
        async for num_captured in observe_value(
            self.driver.written_images_counter, timeout=timeout
        ):
            yield num_captured // self.driver.multiplier

    def get_indices_written(self) -> int:
        return self.driver.written_images_counter
