from __future__ import annotations

from typing import Literal, cast

from ophyd_async.core import (
    Device,
    DeviceConnector,
    DeviceFiller,
    Signal,
    SignalR,
    SignalRW,
    SignalW,
    SignalX,
)
from ophyd_async.core._utils import LazyMock

from ._epics_connector import fill_backend_with_prefix
from ._signal import PvaSignalBackend, pvget_with_timeout

Entry = dict[str, str]

OldPVIVector = list[Entry | None]
# The older PVI structure has vectors of the form
# structure[] ttlout
#     (none)
#     structure
#         string d PANDABLOCKS_IOC:TTLOUT1:PVI
#     structure
#         string d PANDABLOCKS_IOC:TTLOUT2:PVI
#     structure
#         string d PANDABLOCKS_IOC:TTLOUT3:PVI


FastCSPVIVector = dict[Literal["d"], Entry]
# The newer pva FastCS PVI structure has vectors of the form
# structure ttlout
#     structure d
#         string v1 FASTCS_PANDA:Ttlout1:PVI
#         string v2 FASTCS_PANDA:Ttlout2:PVI
#         string v3 FASTCS_PANDA:Ttlout3:PVI
#         string v4 FASTCS_PANDA:Ttlout4:PVI


def _get_signal_details(entry: Entry) -> tuple[type[Signal], str, str]:
    match entry:
        case {"r": read_pv, "w": write_pv}:
            return SignalRW, read_pv, write_pv
        case {"r": read_pv}:
            return SignalR, read_pv, read_pv
        case {"w": write_pv}:
            return SignalW, write_pv, write_pv
        case {"rw": read_write_pv}:
            return SignalRW, read_write_pv, read_write_pv
        case {"x": execute_pv}:
            return SignalX, execute_pv, execute_pv
        case _:
            raise TypeError(f"Can't process entry {entry}")


def _is_device_vector_entry(entry: Entry | OldPVIVector | FastCSPVIVector) -> bool:
    return isinstance(entry, list) or (
        entry.keys() == {"d"} and isinstance(entry["d"], dict)
    )


class PviDeviceConnector(DeviceConnector):
    """Connect to PVI structure served over PVA.

    At init, fill in all the type hinted signals. At connection check their
    types and fill in any extra signals.

    :param prefix:
        The PV prefix of the device, "PVI" will be appended to it to get the PVI
        PV.
    :param error_hint:
        If given, this will be appended to the error message if any of they type
        hinted Signals are not present.
    """

    mock_device_vector_len: int = 2

    def __init__(self, prefix: str = "", error_hint: str = "") -> None:
        # TODO: what happens if we get a leading "pva://" here?
        self.prefix = prefix
        self.pvi_pv = prefix + "PVI"
        self.error_hint = error_hint

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
        self.filler.create_device_vector_entries_to_mock(self.mock_device_vector_len)
        # Set the name of the device to name all children
        device.set_name(device.name)
        return await super().connect_mock(device, mock)

    def _fill_vector_child(self, name: str, entry: OldPVIVector | FastCSPVIVector):
        if isinstance(entry, list):
            for i, e in enumerate(entry):
                if e:
                    self._fill_child(name, e, i)
        else:
            for i_string, e in entry["d"].items():
                self._fill_child(name, {"d": e}, int(i_string.lstrip("v")))

    async def connect_real(
        self, device: Device, timeout: float, force_reconnect: bool
    ) -> None:
        pvi_structure = await pvget_with_timeout(self.pvi_pv, timeout)

        entries: dict[str, Entry | OldPVIVector | FastCSPVIVector] = pvi_structure[
            "value"
        ].todict()
        # Fill based on what PVI gives us
        for name, entry in entries.items():
            if _is_device_vector_entry(entry):
                self._fill_vector_child(
                    name, cast(OldPVIVector | FastCSPVIVector, entry)
                )
            else:
                # This is a child
                self._fill_child(name, cast(Entry, entry))

        # Check that all the requested children have been filled
        suffix = f"\n{self.error_hint}" if self.error_hint else ""
        self.filler.check_filled(f"{self.pvi_pv}: {entries}{suffix}")
        # Set the name of the device to name all children
        device.set_name(device.name)
        return await super().connect_real(device, timeout, force_reconnect)
