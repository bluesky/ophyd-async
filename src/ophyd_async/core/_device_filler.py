from __future__ import annotations

import re
from typing import Generic, NoReturn, TypeVar, get_args, get_origin, get_type_hints

from ._device import Device, DeviceConnector, DeviceVector
from ._signal import Signal, SignalX
from ._signal_backend import SignalBackend
from ._utils import get_origin_class


def _strip_number_from_string(string: str) -> tuple[str, int | None]:
    match = re.match(r"(.*?)(\d*)$", string)
    assert match

    name = match.group(1)
    number = match.group(2) or None
    if number is None:
        return name, None
    else:
        return name, int(number)


SignalBackendT = TypeVar("SignalBackendT", bound=SignalBackend)
DeviceConnectorT = TypeVar("DeviceConnectorT", bound=DeviceConnector)


class DeviceFiller(Generic[SignalBackendT, DeviceConnectorT]):
    def __init__(
        self,
        device: Device,
        signal_backend_type: type[SignalBackendT],
        device_connector_type: type[DeviceConnectorT],
    ):
        self._device = device
        self._signal_backend_type = signal_backend_type
        self._device_connector_type = device_connector_type
        self._vectors: dict[str, DeviceVector] = {}
        self._vector_device_type: dict[str, type[Device] | None] = {}
        self._signal_backends: dict[str, tuple[SignalBackendT, type[Signal]]] = {}
        self._device_connectors: dict[str, DeviceConnectorT] = {}
        # Get type hints on the class, not the instance
        # https://github.com/python/cpython/issues/124840
        self._annotations = get_type_hints(type(device))
        for name, annotation in self._annotations.items():
            # names have a trailing underscore if the clash with a bluesky verb,
            # so strip this off to get what the CS will provide
            stripped_name = name.rstrip("_")
            origin = get_origin_class(annotation)
            if name == "parent" or name.startswith("_") or not origin:
                # Ignore
                pass
            elif issubclass(origin, Signal):
                # SignalX doesn't need datatype, all others need one
                datatype = self.get_datatype(name)
                if origin != SignalX and datatype is None:
                    self._raise(
                        name,
                        f"Expected SignalX or SignalR/W/RW[type], got {annotation}",
                    )
                self._signal_backends[stripped_name] = (
                    self.make_child_signal(name, origin),
                    origin,
                )
            elif origin == DeviceVector:
                # DeviceVector needs a type of device
                args = get_args(annotation) or [None]
                child_origin = get_origin(args[0]) or args[0]
                if child_origin is None or not issubclass(child_origin, Device):
                    self._raise(
                        name,
                        f"Expected DeviceVector[SomeDevice], got {annotation}",
                    )
                self.make_device_vector(name, child_origin)
            elif issubclass(origin, Device):
                self._device_connectors[stripped_name] = self.make_child_device(
                    name, origin
                )

    def unfilled(self) -> set[str]:
        return set(self._device_connectors).union(self._signal_backends)

    def _raise(self, name: str, error: str) -> NoReturn:
        raise TypeError(f"{type(self._device).__name__}.{name}: {error}")

    def make_device_vector(self, name: str, device_type: type[Device] | None):
        self._vectors[name] = DeviceVector({})
        self._vector_device_type[name] = device_type
        setattr(self._device, name, self._vectors[name])

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
                self.make_device_vector(basename, None)

    def get_datatype(self, name: str) -> type | None:
        # Get dtype from SignalRW[dtype] or DeviceVector[SignalRW[dtype]]
        basename, _ = _strip_number_from_string(name)
        if basename in self._vectors:
            # We decided to put it in a device vector, so get datatype from that
            annotation = self._annotations.get(basename, None)
            if annotation:
                annotation = get_args(annotation)[0]
        else:
            # It's not a device vector, so get it from the full name
            annotation = self._annotations.get(name, None)
        args = get_args(annotation)
        if args and get_origin_class(args[0]):
            return args[0]

    def make_child_signal(self, name: str, signal_type: type[Signal]) -> SignalBackendT:
        if name in self._signal_backends:
            # We made it above
            backend, expected_signal_type = self._signal_backends.pop(name)
        else:
            # We need to make a new one
            basename, number = _strip_number_from_string(name)
            child = getattr(self._device, name, None)
            backend = self._signal_backend_type(self.get_datatype(name))
            signal = signal_type(backend)
            if basename in self._vectors and isinstance(number, int):
                # We need to add a new entry to an existing DeviceVector
                expected_signal_type = self._vector_device_type[basename] or signal_type
                self._vectors[basename][number] = signal
            elif child is None:
                # We need to add a new child to the top level Device
                expected_signal_type = signal_type
                setattr(self._device, name, signal)
            else:
                self._raise(name, f"Cannot make child as it would shadow {child}")
        if signal_type is not expected_signal_type:
            self._raise(
                name,
                f"is a {signal_type.__name__} not a {expected_signal_type.__name__}",
            )
        return backend

    def make_child_device(
        self, name: str, device_type: type[Device] = Device
    ) -> DeviceConnectorT:
        basename, number = _strip_number_from_string(name)
        child = getattr(self._device, name, None)
        if connector := self._device_connectors.pop(name, None):
            # We made it above
            return connector
        elif basename in self._vectors and isinstance(number, int):
            # We need to add a new entry to an existing DeviceVector
            vector_device_type = self._vector_device_type[basename] or device_type
            assert issubclass(
                vector_device_type, Device
            ), f"{vector_device_type} is not a Device"
            connector = self._device_connector_type()
            device = vector_device_type(connector=connector)
            self._vectors[basename][number] = device
        elif child is None:
            # We need to add a new child to the top level Device
            connector = self._device_connector_type()
            device = device_type(connector=connector)
            setattr(self._device, name, device)
        else:
            self._raise(name, f"Cannot make child as it would shadow {child}")
        connector.create_children_from_annotations(device)
        return connector

    def make_soft_device_vector_entries(self, num: int):
        for basename, cls in self._vector_device_type.items():
            assert cls, "Shouldn't happen"
            for i in range(num):
                name = f"{basename}{i + 1}"
                if issubclass(cls, Signal):
                    self.make_child_signal(name, cls)
                elif issubclass(cls, Device):
                    self.make_child_device(name, cls)
                else:
                    self._raise(name, f"Can't make {cls}")
