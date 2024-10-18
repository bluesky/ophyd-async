from __future__ import annotations

from unittest.mock import Mock

from ophyd_async.core import (
    Device,
    DeviceConnector,
    DeviceFiller,
    Signal,
    SignalR,
    SignalRW,
    SignalX,
)

from ._epics_connector import fill_backend_with_prefix
from ._p4p import PvaSignalBackend, pvget_with_timeout


def _get_signal_details(entry: dict[str, str]) -> tuple[type[Signal], str, str]:
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
    def __init__(self, prefix: str = "", pvi_pv: str = "") -> None:
        self.prefix = prefix
        self.pvi_pv = pvi_pv

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

    async def connect(
        self, device: Device, mock: bool | Mock, timeout: float, force_reconnect: bool
    ) -> None:
        if mock:
            # Make 2 entries for each DeviceVector
            self.filler.create_device_vector_entries_to_mock(2)
        else:
            pvi_structure = await pvget_with_timeout(self.pvi_pv, timeout)
            entries: dict[str, dict[str, str]] = pvi_structure["value"].todict()
            # Ensure we have device vectors for everything that should be there
            self.filler.ensure_device_vectors(list(entries))
            for name, entry in entries.items():
                if set(entry) == {"d"}:
                    connector = self.filler.fill_child_device(name)
                    connector.pvi_pv = entry["d"]
                else:
                    signal_type, read_pv, write_pv = _get_signal_details(entry)
                    backend = self.filler.fill_child_signal(name, signal_type)
                    backend.read_pv = read_pv
                    backend.write_pv = write_pv
            # Check that all the requested children have been filled
            self.filler.check_filled(f"{self.pvi_pv}: {entries}")
        # Set the name of the device to name all children
        device.set_name(device.name)
        return await super().connect(device, mock, timeout, force_reconnect)
