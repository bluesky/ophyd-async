from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Self

from ophyd_async.core import Device, DeviceConnector, SignalBackend
from ophyd_async.core._device_filler import DeviceFiller
from ophyd_async.epics.signal._signal import CaSignalBackend, PvaSignalBackend


class DeviceAnnotation:
    @abstractmethod
    def __call__(self, parent: Device, child: Device): ...


class EpicsDevice(Device):
    pass


@dataclass
class EpicsSignalSuffix:
    read_suffix: str
    write_suffix: str | None = None

    @classmethod
    def rbv(cls, write_suffix: str, rbv_suffix: str = "_RBV") -> Self:
        return cls(write_suffix + rbv_suffix, write_suffix)


class EpicsDeviceConnector(DeviceConnector):
    def __init__(self, prefix: str, use_pvi: bool) -> None:
        self.prefix = prefix

    def create_children_from_annotations(self, device: Device):
        self._filler = DeviceFiller(device, signal_backend_type=CaSignalBackend, device_connector_type=DeviceConnector)
        for backend, annotations in self._filler.make_signals_from_annotations():
            unhandled = []
            while annotation := annotations.pop(None):
                if isinstance(annotation, EpicsSignalSuffix):
                    backend.read_pv = 




        return super().create_children_from_annotations(device)

    def connect(
        self, device: Device, mock: bool, timeout: float, force_reconnect: bool
    ):
        return super().connect(device, mock, timeout, force_reconnect)
