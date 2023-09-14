import asyncio
import collections
import time
from typing import Callable, Dict, Iterator, Optional, Sized

from bluesky.protocols import (
    Asset,
    Descriptor,
    Flyable,
    PartialEvent,
    WritesExternalAssets,
)
from bluesky.utils import new_uid
from event_model import compose_stream_resource

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    StandardReadable,
    set_and_wait_for_value,
)

from .ad_driver import ADDriver
from .directory_provider import DirectoryProvider
from .nd_file_hdf import NDFileHDF
from .utils import FileWriteMode, ImageMode

# How long in seconds to wait between flushes of HDF datasets
FLUSH_PERIOD = 0.5

# How long to wait for new frames before timing out
FRAME_TIMEOUT = 120


class _HDFResource:
    def __init__(self) -> None:
        # TODO: set to Deque[Asset] after protocols updated for stream*
        #   https://github.com/bluesky/bluesky/issues/1558
        self.asset_docs = collections.deque()  # type: ignore
        self._last_emitted = 0
        self._last_flush = time.monotonic()
        self._compose_datum: Optional[Callable] = None

    def _append_resource(self, full_file_name: str):
        resource_doc, (self._compose_datum,) = compose_stream_resource(
            spec="AD_HDF5_SWMR_SLICE",
            root="/",
            resource_path=full_file_name,
            resource_kwargs={},
            stream_names=["primary"],
        )
        self.asset_docs.append(("stream_resource", resource_doc))

    def _append_datum(self, event_count: int):
        assert self._compose_datum, "Resource not emitted yet"
        datum_doc = self._compose_datum(
            datum_kwargs={},
            event_offset=self._last_emitted,
            event_count=event_count,
        )
        self._last_emitted += event_count
        self.asset_docs.append(("stream_datum", datum_doc))

    async def flush_and_publish(self, hdf: NDFileHDF):
        num_captured = await hdf.num_captured.get_value()
        if num_captured:
            if self._compose_datum is None:
                self._append_resource(await hdf.full_file_name.get_value())
            event_count = num_captured - self._last_emitted
            if event_count:
                self._append_datum(event_count)
                await hdf.flush_now.set(True)
                self._last_flush = time.monotonic()
        if time.monotonic() - self._last_flush > FRAME_TIMEOUT:
            raise TimeoutError(f"{hdf.name}: writing stalled on frame {num_captured}")


class HDFStreamerDet(StandardReadable, Flyable, WritesExternalAssets):
    def __init__(
        self, drv: ADDriver, hdf: NDFileHDF, dp: DirectoryProvider, name=""
    ) -> None:
        self.drv = drv
        self.hdf = hdf
        self._dp = dp
        self._resource = _HDFResource()
        self._capture_status: Optional[AsyncStatus] = None
        self._start_status: Optional[AsyncStatus] = None
        self.set_readable_signals(config=[self.drv.acquire_time])
        super().__init__(name)

    @AsyncStatus.wrap
    async def stage(self) -> None:
        # Make a new resource for the new HDF file we're going to open
        self._resource = _HDFResource()
        await asyncio.gather(
            self.drv.wait_for_plugins.set(True),
            self.hdf.lazy_open.set(True),
            self.hdf.swmr_mode.set(True),
            self.hdf.file_path.set(str(await self._dp.get_directory())),
            self.hdf.file_name.set(f"{self.name}-{new_uid()}"),
            self.hdf.file_template.set("%s/%s.h5"),
            # Go forever
            self.hdf.num_capture.set(0),
            self.hdf.file_write_mode.set(FileWriteMode.stream),
        )
        # Wait for it to start, stashing the status that tells us when it finishes
        self._capture_status = await set_and_wait_for_value(self.hdf.capture, True)
        await super().stage()

    async def describe(self) -> Dict[str, Descriptor]:
        datakeys = await super().describe()
        # Insert a descriptor for the HDF resource, this will not appear
        # in read() as it describes StreamResource outputs only
        datakeys[self.name] = Descriptor(
            source=self.hdf.full_file_name.source,
            shape=await asyncio.gather(
                self.drv.array_size_y.get_value(),
                self.drv.array_size_x.get_value(),
            ),
            dtype="array",
            external="STREAM:",
        )
        return datakeys

    # For step scan, take a single frame
    @AsyncStatus.wrap
    async def trigger(self):
        await self.drv.image_mode.set(ImageMode.single)
        frame_timeout = DEFAULT_TIMEOUT + await self.drv.acquire_time.get_value()
        await self.drv.acquire.set(1, timeout=frame_timeout)
        await self._resource.flush_and_publish(self.hdf)

    def collect_asset_docs(self) -> Iterator[Asset]:
        while self._resource.asset_docs:
            yield self._resource.asset_docs.popleft()

    # For flyscan, take the number of frames we wanted
    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        await self.drv.image_mode.set(ImageMode.multiple)
        # Wait for it to start, stashing the status that tells us when it finishes
        self._start_status = await set_and_wait_for_value(self.drv.acquire, True)

    # Do the same thing for flyscans and step scans
    async def describe_collect(self) -> Dict[str, Dict[str, Descriptor]]:
        return {self.name: await self.describe()}

    def collect(self) -> Iterator[PartialEvent]:
        yield from iter([])

    @AsyncStatus.wrap
    async def complete(self) -> None:
        done: Sized = ()
        while not done:
            assert self._start_status, "Kickoff not run"
            done, _ = await asyncio.wait(
                (self._start_status.task,), timeout=FLUSH_PERIOD
            )
            await self._resource.flush_and_publish(self.hdf)

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        # Already done a caput callback in _capture_status, so can't do one here
        await self.hdf.capture.set(False, wait=False)
        assert self._capture_status, "Stage not run"
        await self._capture_status
        await super().unstage()
