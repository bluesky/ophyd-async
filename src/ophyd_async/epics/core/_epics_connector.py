from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ophyd_async.core import Device, DeviceConnector, DeviceFiller

from ._signal import EpicsSignalBackend, get_signal_backend_type, split_protocol_from_pv


@dataclass
class PvSuffix:
    """Define the PV suffix to be appended to the device prefix."""

    read_suffix: str
    write_suffix: str | None = None

    @classmethod
    def rbv(cls, write_suffix: str, rbv_suffix: str = "_RBV") -> PvSuffix:
        return cls(write_suffix + rbv_suffix, write_suffix)


def fill_backend_with_prefix(
    prefix: str, backend: EpicsSignalBackend, annotations: list[Any]
):
    unhandled = []
    while annotations:
        annotation = annotations.pop(0)
        if isinstance(annotation, PvSuffix):
            backend.read_pv = prefix + annotation.read_suffix
            backend.write_pv = prefix + (
                annotation.write_suffix or annotation.read_suffix
            )
        else:
            unhandled.append(annotation)
    annotations.extend(unhandled)
    # These leftover annotations will now be handled by the iterator


class EpicsDeviceConnector(DeviceConnector):
    """Used for connecting signals to static EPICS pvs."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def create_children_from_annotations(self, device: Device):
        if not hasattr(self, "filler"):
            protocol, prefix = split_protocol_from_pv(self.prefix)
            self.filler = DeviceFiller(
                device,
                signal_backend_factory=get_signal_backend_type(protocol),
                device_connector_factory=DeviceConnector,
            )
            for backend, annotations in self.filler.create_signals_from_annotations():
                fill_backend_with_prefix(prefix, backend, annotations)

            list(self.filler.create_devices_from_annotations())
