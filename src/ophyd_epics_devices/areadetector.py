import asyncio
import collections
import time
from enum import Enum
from typing import AsyncIterator, Callable, Deque, Dict, Iterator, Optional, Sized, Type

from bluesky.protocols import (
    Asset,
    Datum,
    Descriptor,
    Flyable,
    PartialEvent,
    Reading,
    Triggerable,
    WritesExternalAssets,
)
from event_model import compose_resource, compose_stream_resource
from ophyd.v2.core import (
    AsyncReadable,
    AsyncStatus,
    Device,
    SignalR,
    SignalRW,
    StandardReadable,
    T,
    wait_for_value,
)
from ophyd.v2.epics import epics_signal_r, epics_signal_rw


def ad_rw(datatype: Type[T], prefix: str) -> SignalRW[T]:
    return epics_signal_rw(datatype, prefix + "_RBV", prefix)


def ad_r(datatype: Type[T], prefix: str) -> SignalR[T]:
    return epics_signal_r(datatype, prefix + "_RBV")


class ImageMode(Enum):
    single = "Single"
    multiple = "Multiple"
    continuous = "Continuous"


class ADDriver(Device):
    def __init__(self, prefix: str) -> None:
        # Define some signals
        self.acquire = ad_rw(bool, prefix + "Acquire")
        self.acquire_time = ad_rw(float, prefix + "AcquireTime")
        self.num_images = ad_rw(int, prefix + "NumImages")
        self.image_mode = ad_rw(ImageMode, prefix + "ImageMode")
        self.array_counter = ad_rw(int, prefix + "ArrayCounter")
        self.array_size_x = ad_r(int, prefix + "ArraySizeX")
        self.array_size_y = ad_r(int, prefix + "ArraySizeY")
        # There is no _RBV for this one
        self.wait_for_plugins = epics_signal_rw(bool, prefix + "WaitForPlugins")


class NDPluginStats(Device):
    def __init__(self, prefix: str) -> None:
        # Define some signals
        self.unique_id = ad_r(int, prefix + "UniqueId")


class MySingleTriggerSim(StandardReadable, Triggerable):
    def __init__(self, prefix: str, name="") -> None:
        # Define some plugins
        self.drv = ADDriver(prefix + "CAM:")
        self.stats = NDPluginStats(prefix + "STAT:")
        super().__init__(
            name,
            # Can't subscribe to read signals as race between monitor coming back and
            # caput callback on acquire
            read_uncached=[self.drv.array_counter, self.stats.unique_id],
            config=[self.drv.acquire_time],
        )

    @AsyncStatus.wrap
    async def stage(self) -> None:
        await asyncio.gather(
            self.drv.image_mode.set(ImageMode.single),
            self.drv.wait_for_plugins.set(True),
        )
        super().stage()

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        await self.drv.acquire.set(1)


class FileWriteMode(str, Enum):
    single = "Single"
    capture = "Capture"
    stream = "Stream"


class NDFileHDF(Device):
    def __init__(self, prefix: str) -> None:
        # Define some signals
        self.file_path = ad_rw(str, prefix + "FilePath")
        self.file_name = ad_rw(str, prefix + "FileName")
        self.file_template = ad_rw(str, prefix + "FileTemplate")
        self.full_file_name = ad_r(str, prefix + "FullFileName")
        self.file_write_mode = ad_rw(FileWriteMode, prefix + "FileWriteMode")
        self.num_capture = ad_rw(int, prefix + "NumCapture")
        self.num_captured = ad_r(int, prefix + "NumCaptured")
        self.swmr_mode = ad_rw(bool, prefix + "SWMRMode")
        self.lazy_open = ad_rw(bool, prefix + "LazyOpen")
        self.capture = ad_rw(bool, prefix + "Capture")
        self.flush_now = epics_signal_rw(bool, prefix + "FlushNow")
        self.array_size0 = ad_r(int, prefix + "ArraySize0")
        self.array_size1 = ad_r(int, prefix + "ArraySize1")


class HDFResource(AsyncReadable):
    def __init__(self, hdf: NDFileHDF):
        self.hdf = hdf
        self._compose_datum: Optional[Callable] = None
        self._datum: Optional[Datum] = None

    async def create_asset_docs(self) -> AsyncIterator[Asset]:
        num_captured = await self.hdf.num_captured.get_value()
        if num_captured == 1:
            # First frame, get filename and make resource from it
            resource_doc, self._compose_datum, _ = compose_resource(
                # AD_HDF5 means primary dataset must be /entry/data/data
                spec="AD_HDF5",
                root="/",
                resource_path=await self.hdf.full_file_name.get_value(),
                resource_kwargs=dict(frame_per_point=1),
            )
            yield "resource", resource_doc
        assert self._compose_datum, "We haven't made a resource yet"
        self._datum = self._compose_datum(datum_kwargs=dict(point_number=num_captured))
        assert self._datum, "That went wrong"
        yield "datum", self._datum

    async def describe(self) -> Dict[str, Descriptor]:
        # This will be called after trigger, so a frame will have been pushed through
        # and the array size PVs are valid
        descriptor: Descriptor = dict(
            source=self.hdf.full_file_name.source,
            shape=await asyncio.gather(
                self.hdf.array_size1.get_value(), self.hdf.array_size0.get_value()
            ),
            dtype="array",
            external="FILESTORE:",
        )
        return {"": descriptor}

    async def read(self) -> Dict[str, Reading]:
        assert self._datum, "Trigger not called yet"
        reading: Reading = dict(
            value=self._datum["datum_id"],
            timestamp=time.time(),
        )
        return {"": reading}


class MyHDFWritingSim(StandardReadable, Triggerable, WritesExternalAssets):
    def __init__(self, prefix: str, name="") -> None:
        # Define some plugins
        self.drv = ADDriver(prefix + "CAM:")
        self.hdf = NDFileHDF(prefix + "HDF5:")
        self.resource = HDFResource(self.hdf)
        self._capture_status: Optional[asyncio.Task] = None
        self._asset_docs: Deque[Asset] = collections.deque()
        self._datum: Optional[Datum] = None
        super().__init__(name, primary=self.resource, config=[self.drv.acquire_time])

    @AsyncStatus.wrap
    async def stage(self) -> None:
        await asyncio.gather(
            self.drv.image_mode.set(ImageMode.single),
            self.drv.wait_for_plugins.set(True),
            self.hdf.lazy_open.set(True),
            self.hdf.swmr_mode.set(True),
            self.hdf.file_write_mode.set(FileWriteMode.stream),
        )
        # Go forever
        # Do this separately just to make sure it takes
        await self.hdf.num_capture.set(0)
        self._capture_status = self.hdf.capture.set(1)
        super().stage()

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        await self.drv.acquire.set(1)
        async for asset in self.resource.create_asset_docs():
            self._asset_docs.append(asset)

    def collect_asset_docs(self) -> Iterator[Asset]:
        while self._asset_docs:
            yield self._asset_docs.popleft()

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        # Already done a caput callback in _capture_status, so can't do one here
        await self.hdf.capture.set(0, wait=False)
        assert self._capture_status, "Trigger not run"
        await self._capture_status
        super().unstage()


# How long in seconds to wait between flushes of HDF datasets
FLUSH_PERIOD = 0.5


class MyHDFFlyerSim(StandardReadable, Flyable, WritesExternalAssets):
    def __init__(self, prefix: str, name="") -> None:
        # Define some plugins
        self.drv = ADDriver(prefix + "CAM:")
        self.hdf = NDFileHDF(prefix + "HDF5:")
        # TODO add support to bluesky.protocols for StreamDatum and StreamResource
        # then the following type ignore can be removed
        self._asset_docs = collections.deque()  # type: ignore
        self._capture_status: Optional[AsyncStatus] = None
        self._start_status: Optional[AsyncStatus] = None
        self._compose_datum: Optional[Callable] = None
        super().__init__(name, config=[self.drv.acquire_time])

    @AsyncStatus.wrap
    async def stage(self) -> None:
        await asyncio.gather(
            self.drv.image_mode.set(ImageMode.multiple),
            self.drv.wait_for_plugins.set(True),
            self.hdf.lazy_open.set(True),
            self.hdf.swmr_mode.set(True),
            # Go forever
            self.hdf.num_capture.set(0),
            self.hdf.file_write_mode.set(FileWriteMode.stream),
        )
        self._compose_datum = None
        super().stage()

    async def describe_collect(self) -> Dict[str, Dict[str, Descriptor]]:
        desc: Descriptor = dict(
            source=self.hdf.file_path.source,
            shape=await asyncio.gather(
                self.hdf.array_size1.get_value(), self.hdf.array_size0.get_value()
            ),
            dtype="array",
            external="STREAM:",
        )
        return {"primary": {self.name: desc}}

    def collect_asset_docs(self) -> Iterator[Asset]:
        while self._asset_docs:
            yield self._asset_docs.popleft()

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        self._capture_status = self.hdf.capture.set(1)
        # Wait for up to 1s it actually to start
        await wait_for_value(self.hdf.capture, True, timeout=1)
        # TODO: calculate sensible timeout here
        self._start_status = self.drv.acquire.set(1, timeout=100)

    async def _flush_and_publish(self, last_emitted: int) -> int:
        num_captured = await self.hdf.num_captured.get_value()
        if num_captured:
            if self._compose_datum is None:
                resource_doc, (self._compose_datum,) = compose_stream_resource(
                    spec="AD_HDF5_SWMR_SLICE",
                    root="/",
                    resource_path=await self.hdf.full_file_name.get_value(),
                    resource_kwargs={},
                    stream_names=["primary"],
                )
                self._asset_docs.append(("stream_resource", resource_doc))
            event_count = num_captured - last_emitted
            if event_count:
                datum_doc = self._compose_datum(
                    datum_kwargs={}, event_count=event_count, event_offset=last_emitted
                )
                last_emitted = num_captured
                self._asset_docs.append(("stream_datum", datum_doc))
            # Make sure the file is flushed to show the frames
            await self.hdf.flush_now.set(1)
        return num_captured

    @AsyncStatus.wrap
    async def complete(self) -> None:
        done: Sized = ()
        last_emitted = 0
        while not done:
            last_emitted = await self._flush_and_publish(last_emitted)
            # TODO: add stalled timeout
            assert self._start_status, "Kickoff not run"
            done, _ = await asyncio.wait(
                (self._start_status.task,), timeout=FLUSH_PERIOD
            )
        # One last flush and we're done
        await self._flush_and_publish(last_emitted)

    def collect(self) -> Iterator[PartialEvent]:
        # TODO: make this optional now
        return
        yield

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        # Already done a caput callback in _capture_status, so can't do one here
        await self.hdf.capture.set(0, wait=False)
        assert self._capture_status, "Kickoff not run"
        await self._capture_status
        super().unstage()
