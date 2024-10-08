from __future__ import annotations

import re
from typing import Any, NoReturn, get_args, get_origin, get_type_hints

from ophyd_async.core import (
    Device,
    DeviceVector,
    Signal,
    SignalR,
    SignalRW,
    SignalX,
)
from ophyd_async.core._device import DeviceChildConnector
from ophyd_async.core._signal_backend import (
    SignalConnector,
)
from ophyd_async.core._soft_signal_backend import SoftSignalConnector
from ophyd_async.epics.signal._p4p import (
    PvaSignalConnector,
    pvget_with_timeout,
)


def _strip_number_from_string(string: str) -> tuple[str, int | None]:
    match = re.match(r"(.*?)(\d*)$", string)
    assert match

    name = match.group(1)
    number = match.group(2) or None
    if number is None:
        return name, None
    else:
        return name, int(number)


def get_signal_details(entry: dict[str, str]) -> tuple[type[Signal], str, str]:
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


def get_origin_class(annotatation: Any) -> type | None:
    origin = get_origin(annotatation) or annotatation
    if isinstance(origin, type):
        return origin


class DeviceFiller:
    def __init__(self, device: Device):
        self.blank_devices: dict[str, Device] = {}
        self._device = device
        self._vector_children: dict[str, dict] = {}
        self._vector_cls: dict[str, type[Device] | None] = {}
        # Get type hints on the class, not the instance
        # https://github.com/python/cpython/issues/124840
        self._annotations = get_type_hints(type(self._device))
        self.fill_in_blank_devices()

    def fill_in_blank_devices(self):
        for name, annotation in self._annotations.items():
            origin = get_origin_class(annotation)
            if origin and issubclass(origin, Signal):
                # SignalX doesn't need datatype, all others need one
                datatype = self.get_datatype(name)
                if origin != SignalX and datatype is None:
                    self._raise(
                        name,
                        f"Expected SignalX or SignalR/W/RW[type], got {annotation}",
                    )
                signal = origin(SoftSignalConnector(datatype or float))
                self._add_to_device(name, signal)
                self.blank_devices[name] = signal
            elif origin == DeviceVector:
                # DeviceVector needs a type of device
                args = get_args(annotation) or [None]
                child_origin = get_origin(args[0]) or args[0]
                if child_origin is None or not issubclass(child_origin, Device):
                    self._raise(
                        name,
                        f"Expected DeviceVector[SomeDevice], got {annotation}",
                    )
                self._vector_children[name] = {}
                self._vector_cls[name] = child_origin
                self._add_to_device(name, DeviceVector(self._vector_children[name]))
            elif origin and issubclass(origin, Device):
                device = origin()
                self._add_to_device(name, device)
                self.blank_devices[name] = device

    def _raise(self, name: str, error: str) -> NoReturn:
        raise TypeError(f"{type(self._device).__name__}.{name}: {error}")

    def _add_to_device(self, name: str, child: Device):
        if hasattr(self._device, name):
            self._raise(name, "already exists")
        setattr(self._device, name, child)

    def get_datatype(self, name: str) -> type | None:
        # Get dtype from SignalRW[dtype] or DeviceVector[SignalRW[dtype]]
        basename, _ = _strip_number_from_string(name)
        if basename in self._vector_children:
            # We decided to put it in a device vector, so get datatype from that
            annotation = self._annotations.get(basename, None)
            if annotation:
                annotation = get_args(annotation)[0]
        else:
            # It's not a device vector, so get it from the full name
            annotation = self._annotations.get(name, None)
        args = get_args(annotation)
        if args and isinstance(args[0], type):
            return args[0]

    def make_child_device(self, name: str):
        basename, number = _strip_number_from_string(name)
        attr = getattr(self._device, name, None)
        if basename in self._vector_children:
            # We made the device vectors above, so add to it
            device_cls = self._vector_cls[basename] or Device
            if issubclass(device_cls, Signal):
                self._raise(name, "is a Signal not a Device")
            device = device_cls()
            self._vector_children[basename][number] = device
            return device
        elif isinstance(attr, Device):
            # Fill in connector for existing device
            self.blank_devices.pop(name)
            return attr
        elif attr is None:
            # Don't know the type, so make a base Device
            device = Device()
            self._add_to_device(name, device)
            return device
        else:
            raise TypeError(
                f"{type(self._device).__name__}: Cannot make child Device "
                f"{name} as it would shadow {attr}"
            )

    def make_child_signal(
        self, name: str, signal_cls: type[Signal], connector: SignalConnector
    ):
        basename, number = _strip_number_from_string(name)
        attr = getattr(self._device, name, None)
        # TODO: support optional devices...
        if basename in self._vector_children:
            # We made the device vectors above, so add to it
            expected_signal_cls = self._vector_cls[basename] or signal_cls
            if signal_cls is not expected_signal_cls:
                self._raise(
                    name,
                    f"is a {signal_cls.__name__} not a {expected_signal_cls.__name__}",
                )
            signal = signal_cls(connector)
            self._vector_children[basename][number] = signal
        elif isinstance(attr, Signal):
            # Fill in connector for existing signal
            if signal_cls is not type(attr):
                self._raise(
                    name,
                    f"is a {signal_cls.__name__} not a {type(attr).__name__}",
                )
            attr.connect = connector
            self.blank_devices.pop(name)
        elif attr is None:
            # Don't know the type, so make a signal of the guessed type
            self._add_to_device(name, signal_cls(connector))
        else:
            raise TypeError(
                f"{type(self._device).__name__}: Cannot make child Signal "
                f"{name} as it would shadow {attr}"
            )

    def make_device_vectors(self, names: list[str]):
        basenames: dict[str, set[int]] = {}
        for name in names:
            basename, number = _strip_number_from_string(name)
            if number is not None:
                basenames.setdefault(basename, set()).add(number)
        for basename, numbers in basenames.items():
            # If contiguous numbers starting at 1 then it's a device vector
            length = len(numbers)
            if length > 1 and numbers == set(range(1, length + 1)):
                # DeviceVector needs a type of device
                self._vector_children[basename] = {}
                self._vector_cls[basename] = None
                self._add_to_device(
                    basename, DeviceVector(self._vector_children[basename])
                )

    def make_soft_device_vector_entries(self, num: int):
        for basename, cls in self._vector_cls.items():
            assert cls, "Shouldn't happen"
            for i in range(num):
                name = f"{basename}{i+1}"
                if issubclass(cls, Signal):
                    datatype = self.get_datatype(name)
                    self.make_child_signal(
                        name, cls, SoftSignalConnector(datatype or float)
                    )
                else:
                    self.make_child_device(name)


class PviDeviceConnector(DeviceChildConnector):
    def __init__(self, device: Device, pvi_pv: str) -> None:
        self.pvi_pv = pvi_pv
        self._filler = DeviceFiller(device)
        super().__init__(device=device)

    async def connect(self, mock: bool, timeout: float, force_reconnect: bool) -> None:
        if mock:
            # Make 2 entries for each DeviceVector
            self._filler.make_soft_device_vector_entries(2)
        else:
            pvi_structure = await pvget_with_timeout(self.pvi_pv, timeout)
            entries: dict[str, dict[str, str]] = pvi_structure["value"].todict()
            # Ensure we have device vectors for everything that should be there
            self._filler.make_device_vectors(list(entries))
            for name, entry in entries.items():
                if set(entry) == {"d"}:
                    device = self._filler.make_child_device(name)
                    if isinstance(device.connect, PviDeviceConnector):
                        device.connect.pvi_pv = entry["d"]
                    else:
                        device.connect = PviDeviceConnector(device, pvi_pv=entry["d"])
                else:
                    signal_cls, read_pv, write_pv = get_signal_details(entry)
                    datatype = self._filler.get_datatype(name)
                    self._filler.make_child_signal(
                        name,
                        signal_cls,
                        PvaSignalConnector(datatype, read_pv, write_pv),
                    )
            # Check that all the requested children have been created
            if self._filler.blank_devices:
                raise RuntimeError(
                    f"{self._device.name}: PVI cannot provision "
                    f"{set(self._filler.blank_devices)} from {entries}"
                )

        # Make sure children as named
        self._device.set_name(self._device.name)
        return await super().connect(mock, timeout, force_reconnect)
