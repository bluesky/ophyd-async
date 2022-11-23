import asyncio
import collections
import time
from enum import Enum
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Deque,
    Dict,
    Iterator,
    List,
    Optional,
    Sized,
    Type,
)

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
    StandardReadable,
    T,
    wait_for_value,
)
from ophyd.v2.epics import EpicsSignalR, EpicsSignalRW, EpicsSignalX


def ad_rw(datatype: Type[T], suffix: str) -> EpicsSignalRW[T]:
    return EpicsSignalRW(datatype, suffix + "_RBV", suffix)


def ad_r(datatype: Type[T], suffix: str) -> EpicsSignalR[T]:
    return EpicsSignalR(datatype, suffix + "_RBV")


class ImageMode(Enum):
    single = "Single"
    multiple = "Multiple"
    continuous = "Continuous"


class ADDriver(StandardReadable):
    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        self.acquire = ad_rw(int, "Acquire")
        self.acquire_time = ad_rw(float, "AcquireTime")
        self.num_images = ad_rw(int, "NumImages")
        self.image_mode = ad_rw(ImageMode, "ImageMode")
        self.array_counter = ad_rw(int, "ArrayCounter")
        self.array_size_x = ad_r(int, "ArraySizeX")
        self.array_size_y = ad_r(int, "ArraySizeY")
        # There is no _RBV for this one
        self.wait_for_plugins = EpicsSignalRW(bool, "WaitForPlugins")
        super().__init__(prefix, name)


class NDPluginStats(StandardReadable):
    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        self.unique_id = ad_r(int, "UniqueId")
        super().__init__(prefix, name)


class MySingleTriggerSim(StandardReadable, Triggerable):
    def __init__(self, prefix: str, name="") -> None:
        # Define some plugins
        self.drv = ADDriver("CAM:")
        self.stats = NDPluginStats("STAT:")
        self._stage_task: Optional[asyncio.Task] = None
        super().__init__(
            prefix,
            name,
            # Can't subscribe to read signals as race between monitor coming back and
            # caput callback on acquire
            read_uncached=[self.drv.array_counter, self.stats.unique_id],
            config=[self.drv.acquire_time],
        )

    async def _stage(self) -> None:
        await asyncio.gather(
            self.drv.image_mode.set(ImageMode.single),
            self.drv.wait_for_plugins.set(True),
        )

    def stage(self) -> List[Any]:
        self._stage_task = asyncio.create_task(self._stage())
        return super().stage()

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        assert self._stage_task, "Stage not called yet"
        await self._stage_task
        await self.drv.acquire.set(1)


class FileWriteMode(Enum):
    single = "Single"
    capture = "Capture"
    stream = "Stream"


class NDFileHDF(StandardReadable):
    def __init__(self, prefix: str, name="") -> None:
        # Define some signals
        self.file_path = ad_rw(str, "FilePath")
        self.file_name = ad_rw(str, "FileName")
        self.file_template = ad_rw(str, "FileTemplate")
        self.full_file_name = ad_r(str, "FullFileName")
        self.file_write_mode = ad_rw(FileWriteMode, "FileWriteMode")
        self.num_capture = ad_rw(int, "NumCapture")
        self.num_captured = ad_r(int, "NumCaptured")
        self.lazy_open = ad_rw(bool, "LazyOpen")
        self.capture = ad_rw(int, "Capture")
        self.flush_now = EpicsSignalX("FlushNow", write_value=1)
        self.array_size0 = ad_r(int, "ArraySize0")
        self.array_size1 = ad_r(int, "ArraySize1")
        super().__init__(prefix, name)


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
        self.drv = ADDriver("CAM:")
        self.hdf = NDFileHDF("HDF5:")
        self.resource = HDFResource(self.hdf)
        self._stage_task: Optional[asyncio.Task] = None
        self._capture_status: Optional[asyncio.Task] = None
        self._asset_docs: Deque[Asset] = collections.deque()
        self._datum: Optional[Datum] = None
        super().__init__(
            prefix, name, primary=self.resource, config=[self.drv.acquire_time]
        )

    async def _stage(self) -> None:
        await asyncio.gather(
            self.drv.image_mode.set(ImageMode.single),
            self.drv.wait_for_plugins.set(True),
            self.hdf.lazy_open.set(True),
            self.hdf.file_write_mode.set(FileWriteMode.stream),
        )
        # Go forever
        # Do this separately just to make sure it takes
        await self.hdf.num_capture.set(0)
        self._capture_status = self.hdf.capture.set(1)

    def stage(self) -> List[Any]:
        self._stage_task = asyncio.create_task(self._stage())
        return super().stage()

    @AsyncStatus.wrap
    async def trigger(self) -> None:
        assert self._stage_task, "Stage not run"
        await self._stage_task
        await self.drv.acquire.set(1)
        async for asset in self.resource.create_asset_docs():
            self._asset_docs.append(asset)

    def collect_asset_docs(self) -> Iterator[Asset]:
        while self._asset_docs:
            yield self._asset_docs.popleft()

    async def _unstage(self) -> None:
        assert self._stage_task, "Stage not run"
        await self._stage_task
        # Already done a caput callback in _capture_status, so can't do one here
        await self.hdf.capture.set(0, wait=False)
        assert self._capture_status, "Trigger not run"
        await self._capture_status

    def unstage(self) -> List[Any]:
        # TODO: where do we put this task?
        asyncio.create_task(self._unstage())
        return super().unstage()


# How long in seconds to wait between flushes of HDF datasets
FLUSH_PERIOD = 0.5


class MyHDFFlyerSim(StandardReadable, Flyable, WritesExternalAssets):
    def __init__(self, prefix: str, name="") -> None:
        # Define some plugins
        self.drv = ADDriver("CAM:")
        self.hdf = NDFileHDF("HDF5:")
        self._asset_docs: Deque[Asset] = collections.deque()
        self._stage_task: Optional[asyncio.Task] = None
        self._capture_status: Optional[AsyncStatus] = None
        self._start_status: Optional[AsyncStatus] = None
        self._compose_datum: Optional[Callable] = None
        super().__init__(prefix, name, config=[self.drv.acquire_time])

    async def _stage(self) -> None:
        await asyncio.gather(
            self.drv.image_mode.set(ImageMode.multiple),
            self.drv.wait_for_plugins.set(True),
            self.hdf.lazy_open.set(True),
            # Go forever
            self.hdf.num_capture.set(0),
            self.hdf.file_write_mode.set(FileWriteMode.stream),
        )

    def stage(self) -> List[Any]:
        self._stage_task = asyncio.create_task(self._stage())
        return super().stage()

    async def describe_collect(self) -> Dict[str, Dict[str, Descriptor]]:
        desc: Descriptor = dict(
            source=self._init_prefix,
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
        assert self._stage_task, "Stage not run"
        await self._stage_task
        self._capture_status = self.hdf.capture.set(1)
        # Wait for up to 1s it actually to start
        wait_for_value(self.hdf.capture, True, timeout=1)
        self._start_status = self.drv.acquire.set(1)

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
            await self.hdf.flush_now.execute()
        return num_captured

    @AsyncStatus.wrap
    async def complete(self) -> None:
        done: Sized = ()
        last_emitted = 0
        while not done:
            last_emitted = await self._flush_and_publish(last_emitted)
            # TODO: add stalled timeout
            assert self._start_status, "Kickoff not run"
            done, _ = await asyncio.wait((self._start_status,), timeout=FLUSH_PERIOD)
        # One last flush and we're done
        await self._flush_and_publish(last_emitted)

    def collect(self) -> Iterator[PartialEvent]:
        # TODO: make this optional now
        return
        yield

    async def _unstage(self) -> None:
        assert self._stage_task, "Stage not run"
        await self._stage_task
        # Already done a caput callback in _capture_status, so can't do one here
        await self.hdf.capture.set(0, wait=False)
        assert self._capture_status, "Kickoff not run"
        await self._capture_status

    def unstage(self) -> List[Any]:
        # TODO: where do we put this task?
        asyncio.create_task(self._unstage())
        return super().unstage()
