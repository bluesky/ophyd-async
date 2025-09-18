from collections.abc import AsyncGenerator, AsyncIterator
import time
from bluesky.protocols import StreamAsset
from event_model import DataKey  # type: ignore
from ophyd_async.core import YMDPathProvider
from ophyd_async.core import AsyncStatus, DetectorWriter, observe_value, wait_for_value
from ophyd_async.epics.core import epics_signal_r, epics_signal_rw_rbv, epics_signal_rw
from ophyd_async.core import StandardReadable
from ophyd_async.core import SignalRW
import asyncio
class JunfrauCommissioningWriter(DetectorWriter, StandardReadable):
    def __init__(
        self,
        path_provider: YMDPathProvider
    ) -> None:
        with self.add_children_as_readables():
            self._path_info = path_provider
            self.frame_counter = epics_signal_rw(int, "BL24I-JUNGFRAU-META:FD:NumCaptured")
            self.file_name = epics_signal_rw_rbv(str, "BL24I-JUNGFRAU-META:FD:FileName")
            self.file_path = epics_signal_rw_rbv(str, "BL24I-JUNGFRAU-META:FD:FilePath")
            self.writer_ready = epics_signal_r(int, "BL24I-JUNGFRAU-META:FD:Ready_RBV")
        self.pedestal_fudge_factor = 1
        super().__init__()

    async def open(self, name: str, exposures_per_event: int = 1) -> dict[str, DataKey]:
        self._exposures_per_event = exposures_per_event
        await self.file_name.set(self._path_info().filename)
        await self.file_path.set(str(self._path_info().directory_path))
        await self.frame_counter.set(0)
        await wait_for_value(self.writer_ready, 1, timeout=10)
        # start = time.time()
        # _wait_done = False
        # while time.time() - start < 5:
        #     if await self.writer_ready.get_value() == 1:
        #         _wait_done = True
        #         break
        # if not _wait_done:
        #     raise Exception("Timed out waiting for writer ready")
        return await self._describe()

    async def _describe(self) -> dict[str, DataKey]:
        # Dummy function, doesn't actually describe the dataset

        return {
            "data": DataKey(
                source="Commissioning writer",
                shape=[-1],
                dtype="array",
                dtype_numpy="<u2",
                external="STREAM:",
            )
        }

    async def observe_indices_written(
        self, timeout: float
    ) -> AsyncGenerator[int, None]:
        async for num_captured in observe_value(self.frame_counter, timeout):
            print(f"Num cap: {num_captured} exposures: {self._exposures_per_event}")
            yield num_captured // (self._exposures_per_event*self.pedestal_fudge_factor)

    async def get_indices_written(self) -> int:
        return await self.frame_counter.get_value() // self._exposures_per_event

    def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        raise NotImplementedError()

    async def close(self) -> None: ...
