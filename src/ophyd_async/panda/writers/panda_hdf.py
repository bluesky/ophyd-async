from dataclasses import dataclass
from typing import Iterator, List, Tuple

from event_model import StreamDatum, StreamResource, compose_stream_resource

from ophyd_async.core.device import Device
from ophyd_async.epics.signal.signal import epics_signal_r, epics_signal_rw


class PandaHDF(Device):
    def __init__(self, prefix: str, name: str = "", **scalar_datasets: str) -> None:
        # Define some signals
        self.file_path = epics_signal_rw(str, prefix + ":HDF5:FilePath")
        self.file_name = epics_signal_rw(str, prefix + ":HDF5:FileName")
        self.full_file_name = epics_signal_r(str, prefix + ":HDF5:FullFileName")
        self.num_capture = epics_signal_rw(int, prefix + ":HDF5:NumCapture")
        self.num_written = epics_signal_r(int, prefix + ":HDF5:NumWritten_RBV")
        self.capture = epics_signal_rw(
            bool, prefix + ":HDF5:Capturing", prefix + ":HDF5:Capture"
        )
        self.flush_now = epics_signal_rw(bool, prefix + ":HDF5:FlushNow")
        self.capture_signals = {
            ds_name: epics_signal_r(bool, prefix + ":" + ds_path + ":CAPTURE")
            for ds_name, ds_path in scalar_datasets.items()
        }
        self.scalar_datasets = scalar_datasets
        super(PandaHDF, self).__init__(name)

    def children(self) -> Iterator[Tuple[str, Device]]:
        for child in super(PandaHDF, self).children():
            yield child
        for attr_name, attr in self.capture_signals.items():
            yield attr_name, attr


@dataclass
class _HDFDataset:
    device_name: str
    name: str
    path: str
    shape: List[int]
    multiplier: int


class _HDFFile:
    def __init__(self, full_file_name: str, datasets: List[_HDFDataset]) -> None:
        self._last_emitted = 0
        self._bundles = [
            compose_stream_resource(
                spec="AD_HDF5_SWMR_SLICE",
                root="/",
                data_key=f"{ds.device_name}-{ds.name}",
                resource_path=full_file_name,
                resource_kwargs={
                    "name": ds.name,
                    "path": ds.path + ".Value",
                    "multiplier": ds.multiplier,
                },
            )
            for ds in datasets
        ]

    def stream_resources(self) -> Iterator[StreamResource]:
        for bundle in self._bundles:
            yield bundle.stream_resource_doc

    def stream_data(self, indices_written: int) -> Iterator[StreamDatum]:
        # Indices are relative to resource
        if indices_written > self._last_emitted:
            indices = dict(
                start=self._last_emitted,
                stop=indices_written,
            )
            self._last_emitted = indices_written
            for bundle in self._bundles:
                yield bundle.compose_stream_datum(indices)
        return None
