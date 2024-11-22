from __future__ import annotations

from ophyd_async.core import (
    Device,
    DeviceConnector,
    DeviceFiller,
    Signal,
    SignalR,
    SignalRW,
    SignalX,
)
from ophyd_async.core._utils import LazyMock

from ._epics_connector import fill_backend_with_prefix
from ._signal import PvaSignalBackend, pvget_with_timeout

Entry = dict[str, str]


def _get_signal_details(entry: Entry) -> tuple[type[Signal], str, str]:
    match entry:
        case {"r": read_pv}:
            return SignalR, read_pv, read_pv
        case {"r": read_pv, "w": write_pv}:
            return SignalRW, read_pv, write_pv
        case {"rw": read_write_pv}:
            return SignalRW, read_write_pv, read_write_pv
        case {"x": execute_pv}:
            return SignalX, execute_pv, execute_pv
        case _:
            raise TypeError(f"Can't process entry {entry}")


class PviDeviceConnector(DeviceConnector):
    def __init__(self, prefix: str = "") -> None:
        # TODO: what happens if we get a leading "pva://" here?
        self.prefix = prefix
        self.pvi_pv = prefix + "PVI"

    def create_children_from_annotations(self, device: Device):
        if not hasattr(self, "filler"):
            self.filler = DeviceFiller(
                device=device,
                signal_backend_factory=PvaSignalBackend,
                device_connector_factory=PviDeviceConnector,
            )
            # Devices will be created with unfilled PviDeviceConnectors
            list(self.filler.create_devices_from_annotations(filled=False))
            # Signals can be filled in with EpicsSignalSuffix and checked at runtime
            for backend, annotations in self.filler.create_signals_from_annotations(
                filled=False
            ):
                fill_backend_with_prefix(self.prefix, backend, annotations)
            self.filler.check_created()

    def _fill_child(self, name: str, entry: Entry, vector_index: int | None = None):
        if set(entry) == {"d"}:
            connector = self.filler.fill_child_device(name, vector_index=vector_index)
            connector.pvi_pv = entry["d"]
        else:
            signal_type, read_pv, write_pv = _get_signal_details(entry)
            backend = self.filler.fill_child_signal(name, signal_type, vector_index)
            backend.read_pv = read_pv
            backend.write_pv = write_pv

    async def connect_mock(self, device: Device, mock: LazyMock):
        self.filler.create_device_vector_entries_to_mock(2)
        # Set the name of the device to name all children
        device.set_name(device.name)
        return await super().connect_mock(device, mock)

    async def connect_real(
        self, device: Device, timeout: float, force_reconnect: bool
    ) -> None:
        pvi_structure = await pvget_with_timeout(self.pvi_pv, timeout)
        entries: dict[str, Entry | list[Entry | None]] = pvi_structure["value"].todict()
        # Fill based on what PVI gives us
        for name, entry in entries.items():
            if isinstance(entry, dict):
                # This is a child
                self._fill_child(name, entry)
            else:
                # This is a DeviceVector of children
                for i, e in enumerate(entry):
                    if e:
                        self._fill_child(name, e, i)
        # Check that all the requested children have been filled
        self.filler.check_filled(f"{self.pvi_pv}: {entries}")
        # Set the name of the device to name all children
        device.set_name(device.name)
        return await super().connect_real(device, timeout, force_reconnect)
