import asyncio
import atexit
from enum import Enum
from typing import (
    AsyncIterator,
    Callable,
    Dict,
    FrozenSet,
    List,
    Optional,
    Tuple,
    get_type_hints,
)

from bluesky.protocols import Asset, Descriptor, Hints
from p4p.client.thread import Context

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    AsyncStatus,
    DetectorWriter,
    Device,
    DirectoryProvider,
    NameProvider,
    Signal,
    wait_for_value,
)
from ophyd_async.epics.signal import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_w,
    epics_signal_x,
    pvi_get,
)

from .panda_hdf import DataBlock, _HDFDataset, _HDFFile


class SimpleCapture(str, Enum):
    No = "No"
    Value = "Value"


class Capture(str, Enum):
    No = "No"
    Value = "Value"
    Diff = "Diff"
    Sum = "Sum"
    Mean = "Mean"
    Min = "Min"
    Max = "Max"
    MinMax = "Min Max"
    MinMaxMean = "Min Max Mean"


class PandaHDFWriter(DetectorWriter):
    # hdf: DataBlock
    _ctxt: Optional[Context] = None

    @property
    def ctxt(self) -> Context:
        if PandaHDFWriter._ctxt is None:
            PandaHDFWriter._ctxt = Context("pva", nt=False)

            @atexit.register
            def _del_ctxt():
                # If we don't do this we get messages like this on close:
                #   Error in sys.excepthook:
                #   Original exception was:
                PandaHDFWriter._ctxt = None

        return PandaHDFWriter._ctxt

    async def connect(self, sim=False) -> None:
        pvi_info = await pvi_get(self._prefix + ":PVI", self.ctxt) if not sim else {}

        # signals to connect, giving block name, signal name and datatype
        desired_signals: Dict[str, List[Tuple[str, type]]] = {}
        for block_name, block in self._to_capture.items():
            if block_name not in desired_signals:
                desired_signals[block_name] = []
            for signal_name in block:
                desired_signals[block_name].append(
                    (f"{signal_name}_capture", SimpleCapture)
                )
        # add signals from DataBlock using type hints
        if "hdf5" not in desired_signals:
            desired_signals["hdf5"] = []
        for signal_name, hint in get_type_hints(self.hdf5).items():
            dtype = hint.__args__[0]
            desired_signals["hdf5"].append((signal_name, dtype))
        # loop over desired signals and set
        for block_name, block_signals in desired_signals.items():
            if block_name not in pvi_info:
                continue
            if not hasattr(self, block_name):
                setattr(self, block_name, Device())
            block_pvi = await pvi_get(pvi_info[block_name]["d"], self.ctxt)
            block = getattr(self, block_name)
            for signal_name, dtype in block_signals:
                if signal_name not in block_pvi:
                    continue
                signal_pvi = block_pvi[signal_name]
                operations = frozenset(signal_pvi.keys())
                pvs = [signal_pvi[i] for i in operations]
                write_pv = pvs[0]
                read_pv = write_pv if len(pvs) == 1 else pvs[1]
                pv_ctxt = self.ctxt.get(read_pv)
                if dtype is SimpleCapture:  # capture record
                    # some :CAPTURE PVs have only 2 values, many have 9
                    if set(pv_ctxt.value.choices) == set(v.value for v in Capture):
                        dtype = Capture
                signal = self.pvi_mapping[operations](
                    dtype, "pva://" + read_pv, "pva://" + write_pv
                )
                setattr(block, signal_name, signal)
        for block_name in desired_signals.keys():
            block: Device = getattr(self, block_name)
            if block:
                await block.connect(sim=sim)

    def __init__(
        self,
        prefix: str,
        directory_provider: DirectoryProvider,
        name_provider: NameProvider,
        **to_capture: List[str],
    ) -> None:
        self._connected_pvs = Device()
        self._prefix = prefix
        self.hdf5 = DataBlock()  # needs a name
        self._directory_provider = directory_provider
        self._name_provider = name_provider
        self._to_capture = to_capture
        self._capture_status: Optional[AsyncStatus] = None
        self._datasets: List[_HDFDataset] = []
        self._file: Optional[_HDFFile] = None
        self._multiplier = 1
        self.pvi_mapping: Dict[FrozenSet[str], Callable[..., Signal]] = {
            frozenset({"r", "w"}): lambda dtype, rpv, wpv: epics_signal_rw(
                dtype, rpv, wpv
            ),
            frozenset({"rw"}): lambda dtype, rpv, wpv: epics_signal_rw(dtype, rpv, wpv),
            frozenset({"r"}): lambda dtype, rpv, wpv: epics_signal_r(dtype, rpv),
            frozenset({"w"}): lambda dtype, rpv, wpv: epics_signal_w(dtype, wpv),
            frozenset({"x"}): lambda dtype, rpv, wpv: epics_signal_x(wpv),
        }

    async def open(self, multiplier: int = 1) -> Dict[str, Descriptor]:
        self._file = None
        info = self._directory_provider()
        await asyncio.gather(
            self.hdf5.filepath.set(info.directory_path),
            self.hdf5.filename.set(f"{info.filename_prefix}.h5"),
        )

        # Overwrite num_capture to go forever
        await self.hdf5.numcapture.set(0)
        # Wait for it to start, stashing the status that tells us when it finishes
        await self.hdf5.capture.set(True)
        self._capture_status = await wait_for_value(
            self.hdf5.capturing, True, DEFAULT_TIMEOUT
        )
        name = self._name_provider()
        if multiplier > 1:
            raise ValueError(
                "All PandA datasets should be scalar, multiplier should be 1"
            )
        self._multiplier = multiplier
        self._datasets = []

        for block, block_signals in self._to_capture.items():
            for signal in block_signals:
                self._datasets.append(
                    _HDFDataset(
                        name, block, signal, f"{block}:{signal}".upper(), [], multiplier
                    )
                )

        describe = {
            ds.name: Descriptor(
                source=self.hdf5.fullfilename.source,
                shape=ds.shape,
                dtype="array" if ds.shape else "number",
                external="STREAM:",
            )
            for ds in self._datasets
        }
        return describe

    async def wait_for_index(
        self, index: int, timeout: Optional[float] = DEFAULT_TIMEOUT
    ):
        def matcher(value: int) -> bool:
            return value // self._multiplier >= index

        matcher.__name__ = f"index_at_least_{index}"
        await wait_for_value(self.hdf5.numwritten_rbv, matcher, timeout=timeout)

    async def get_indices_written(self) -> int:
        num_written = await self.hdf5.numwritten_rbv.get_value()
        return num_written // self._multiplier

    async def collect_stream_docs(self, indices_written: int) -> AsyncIterator[Asset]:
        # TODO: fail if we get dropped frames
        await self.hdf5.flushnow.set(True)
        if indices_written:
            if not self._file:
                self._file = _HDFFile(
                    await self.hdf5.fullfilename.get_value(), self._datasets
                )
            for doc in self._file.stream_resources():
                ds_name = doc["resource_kwargs"]["name"]
                ds_block = doc["resource_kwargs"]["block"]
                block = getattr(self, ds_block, None)
                if block is not None:
                    capturing = getattr(block, f"{ds_name}_capture")
                    if capturing and await capturing.get_value() != Capture.No:
                        yield "stream_resource", doc
            for doc in self._file.stream_data(indices_written):
                yield "stream_datum", doc

    async def close(self):
        # Already done a caput callback in _capture_status, so can't do one here
        await self.hdf5.capture.set(False, wait=False)
        await wait_for_value(self.hdf5.capturing, False, DEFAULT_TIMEOUT)
        if self._capture_status:
            # We kicked off an open, so wait for it to return
            await self._capture_status

    @property
    def hints(self) -> Hints:
        return {"fields": [self._name_provider()]}
