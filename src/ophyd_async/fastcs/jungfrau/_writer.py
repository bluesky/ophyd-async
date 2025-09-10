from collections.abc import AsyncGenerator, AsyncIterator

from bluesky.protocols import StreamAsset
from event_model import DataKey  # type: ignore
from ophyd_async.core import YMDPathProvider
from ophyd_async.core import AsyncStatus, DetectorWriter, observe_value, wait_for_value
from ophyd_async.epics.core import epics_signal_r, epics_signal_rw


class JunfrauCommissioningWriter(DetectorWriter):
    def __init__(
        self,
        path_provider: YMDPathProvider
    ) -> None:
        self._capture_status: AsyncStatus | None = None
        path_info = path_provider()
        path_info.directory_path()
        self.frame_counter = epics_signal_rw(int, "PV_ADDRESS", "PV_ADDRESS_WRITE")
        self.file_name = epics_signal_rw(str, "PV_ADDRESS", "PV_ADDRESS_WRITE")
        self.file_path = epics_signal_rw(int, "PV_ADDRESS", "PV_ADDRESS_WRITE")
        self.writer_ready = epics_signal_r(bool, "PV_ADDRESS")
        #TODO set PVs based on path info?
        super().__init__()

    async def open(self, name: str, exposures_per_event: int = 1) -> dict[str, DataKey]:
        self._exposures_per_event = exposures_per_event
        await self.frame_counter.set(0)
        await wait_for_value(self.writer_ready, True, timeout=10)
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
            yield num_captured // self._exposures_per_event

    async def get_indices_written(self) -> int:
        return await self.frame_counter.get_value() // self._exposures_per_event

    def collect_stream_docs(
        self, name: str, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        raise NotImplementedError()

    async def close(self) -> None: ...
