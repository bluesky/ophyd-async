import asyncio
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Optional

from bluesky.protocols import DataKey, StreamAsset
from p4p.client.thread import Context

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    DetectorWriter,
    Device,
    DirectoryProvider,
    NameProvider,
    SignalR,
    wait_for_value,
)
from ophyd_async.core.signal import observe_value
from ophyd_async.epics.areadetector.writers.general_hdffile import _HDFDataset, _HDFFile
from ophyd_async.panda import CommonPandaBlocks


class Capture(str, Enum):
    # Capture signals for the HDF Panda
    No = "No"
    Value = "Value"
    Diff = "Diff"
    Sum = "Sum"
    Mean = "Mean"
    Min = "Min"
    Max = "Max"
    MinMax = "Min Max"
    MinMaxMean = "Min Max Mean"


def get_capture_signals(
    block: Device, path_prefix: Optional[str] = ""
) -> Dict[str, SignalR]:
    """Get dict mapping a capture signal's name to the signal itself"""
    if not path_prefix:
        path_prefix = ""
    signals: Dict[str, SignalR[Any]] = {}
    for attr_name, attr in block.children():
        # Capture signals end in _capture, but num_capture is a red herring
        if attr_name == "num_capture":
            continue
        dot_path = f"{path_prefix}{attr_name}"
        if isinstance(attr, SignalR) and attr_name.endswith("_capture"):
            signals[dot_path] = attr
        attr_signals = get_capture_signals(attr, path_prefix=dot_path + ".")
        signals.update(attr_signals)
    return signals


@dataclass
class CaptureSignalWrapper:
    signal: SignalR
    capture_type: Capture


# This should return a dictionary which contains a dict, containing the Capture
# signal object, and the value of that signal
async def get_signals_marked_for_capture(
    capture_signals: Dict[str, SignalR],
) -> Dict[str, CaptureSignalWrapper]:
    # Read signals to see if they should be captured
    do_read = [signal.get_value() for signal in capture_signals.values()]

    signal_values = await asyncio.gather(*do_read)

    assert len(signal_values) == len(
        capture_signals
    ), "Length of read signals are different to length of signals"

    signals_to_capture: Dict[str, CaptureSignalWrapper] = {}
    for signal_path, signal_object, signal_value in zip(
        capture_signals.keys(), capture_signals.values(), signal_values
    ):
        signal_path = signal_path.replace("_capture", "")
        if (signal_value in iter(Capture)) and (signal_value != Capture.No):
            signals_to_capture[signal_path] = CaptureSignalWrapper(
                signal_object,
                signal_value,
            )

    return signals_to_capture


class PandaHDFWriter(DetectorWriter):
    _ctxt: Optional[Context] = None

    def __init__(
        self,
        prefix: str,
        directory_provider: DirectoryProvider,
        name_provider: NameProvider,
        panda_device: CommonPandaBlocks,
    ) -> None:
        self.panda_device = panda_device
        self._prefix = prefix
        self._directory_provider = directory_provider
        self._name_provider = name_provider
        self._datasets: List[_HDFDataset] = []
        self._file: Optional[_HDFFile] = None
        self._multiplier = 1

    # Triggered on PCAP arm
    async def open(self, multiplier: int = 1) -> Dict[str, DataKey]:
        """Retrieve and get descriptor of all PandA signals marked for capture"""

        # Get capture PVs by looking at panda. Gives mapping of dotted attribute path
        # to Signal object
        self.capture_signals = get_capture_signals(self.panda_device)

        # Ensure flushes are immediate
        await self.panda_device.data.flush_period.set(0)

        to_capture = await get_signals_marked_for_capture(self.capture_signals)
        self._file = None
        info = self._directory_provider()
        # Set the initial values
        await asyncio.gather(
            self.panda_device.data.hdf_directory.set(
                str(info.root / info.resource_dir)
            ),
            self.panda_device.data.hdf_file_name.set(
                f"{info.prefix}{self.panda_device.name}{info.suffix}.h5",
            ),
            self.panda_device.data.num_capture.set(0),
        )

        # Wait for it to start, stashing the status that tells us when it finishes
        await self.panda_device.data.capture.set(True)
        name = self._name_provider()
        if multiplier > 1:
            raise ValueError(
                "All PandA datasets should be scalar, multiplier should be 1"
            )
        self._datasets = []
        for attribute_path, capture_signal in to_capture.items():
            split_path = attribute_path.split(".")
            signal_name = split_path[-1]
            # Get block names from numbered blocks, eg INENC[1]
            block_name = (
                f"{split_path[-3]}{split_path[-2]}"
                if split_path[-2].isnumeric()
                else split_path[-2]
            )

            for suffix in capture_signal.capture_type.split(" "):
                self._datasets.append(
                    _HDFDataset(
                        device_name=name,
                        block=block_name,
                        data_key=f"{name}-{block_name}-{signal_name}-{suffix}",
                        dataset=f"{block_name}-{signal_name}".upper() + f"-{suffix}",
                        shape=[1],
                        multiplier=1,
                    )
                )

        describe = {
            ds.data_key: DataKey(
                source=self.panda_device.data.hdf_directory.source,
                shape=ds.shape,
                dtype="array" if ds.shape != [1] else "number",
                external="STREAM:",
            )
            for ds in self._datasets
        }
        return describe

    # Next few functions are exactly the same as AD writer. Could move as default
    # StandardDetector behavior
    async def wait_for_index(
        self, index: int, timeout: Optional[float] = DEFAULT_TIMEOUT
    ):
        def matcher(value: int) -> bool:
            return value >= index

        matcher.__name__ = f"index_at_least_{index}"
        await wait_for_value(
            self.panda_device.data.num_captured, matcher, timeout=timeout
        )

    async def get_indices_written(self) -> int:
        return await self.panda_device.data.num_captured.get_value()

    async def observe_indices_written(
        self, timeout=DEFAULT_TIMEOUT
    ) -> AsyncGenerator[int, None]:
        """Wait until a specific index is ready to be collected"""
        async for num_captured in observe_value(
            self.panda_device.data.num_captured, timeout
        ):
            yield num_captured // self._multiplier

    async def collect_stream_docs(
        self, indices_written: int
    ) -> AsyncIterator[StreamAsset]:
        # TODO: fail if we get dropped frames
        if indices_written:
            if not self._file:
                self._file = _HDFFile(
                    self._directory_provider(),
                    Path(await self.panda_device.data.hdf_file_name.get_value()),
                    self._datasets,
                )
                for doc in self._file.stream_resources():
                    yield "stream_resource", doc
            for doc in self._file.stream_data(indices_written):
                yield "stream_datum", doc

    # Could put this function as default for StandardDetector
    async def close(self):
        await self.panda_device.data.capture.set(
            False, wait=True, timeout=DEFAULT_TIMEOUT
        )
