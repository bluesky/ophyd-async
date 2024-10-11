from __future__ import annotations

import re
from typing import Any, Generic, NoReturn, TypeVar, get_args, get_origin, get_type_hints

from ophyd_async.core import (
    Device,
    DeviceBackend,
    DeviceBase,
    DeviceVector,
    Signal,
    SignalBackend,
    SignalR,
    SignalRW,
    SignalX,
)
from ophyd_async.epics.signal import (
    PvaSignalBackend,
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


SignalBackendT = TypeVar("SignalBackendT", bound=SignalBackend)
DeviceBackendT = TypeVar("DeviceBackendT", bound=DeviceBackend)


class DeviceFiller(Generic[SignalBackendT, DeviceBackendT]):
    def __init__(
        self,
        children: dict[str, DeviceBase],
        device_type: type[Device],
        signal_backend_type: type[SignalBackendT],
        device_backend_type: type[DeviceBackendT],
    ):
        self._children = children
        self._device_type = device_type
        self._signal_backend_type = signal_backend_type
        self._device_backend_type = device_backend_type
        self._vectors: dict[str, DeviceVector] = {}
        self._vector_device_type: dict[str, type[DeviceBase] | None] = {}
        self._signal_backends: dict[str, SignalBackendT] = {}
        self._device_backends: dict[str, DeviceBackendT] = {}
        # Get type hints on the class, not the instance
        # https://github.com/python/cpython/issues/124840
        self._annotations = get_type_hints(device_type)
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
                self._signal_backends[name] = self.make_child_signal(name, origin)
            elif origin == DeviceVector:
                # DeviceVector needs a type of device
                args = get_args(annotation) or [None]
                child_origin = get_origin(args[0]) or args[0]
                if child_origin is None or not issubclass(child_origin, DeviceBase):
                    self._raise(
                        name,
                        f"Expected DeviceVector[SomeDevice], got {annotation}",
                    )
                self.make_device_vector(name, child_origin)
            elif origin and issubclass(origin, Device):
                self._device_backends[name] = self.make_child_device(name, origin)

    def unfilled(self) -> set[str]:
        return set(self._device_backends).union(self._signal_backends)

    def _raise(self, name: str, error: str) -> NoReturn:
        raise TypeError(f"{self._device_type.__name__}.{name}: {error}")

    def make_device_vector(self, name: str, device_type: type[DeviceBase] | None):
        self._vectors[name] = DeviceVector({})
        self._vector_device_type[name] = device_type
        self._children[name] = self._vectors[name]

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
        if args and isinstance(args[0], type):
            return args[0]

    def make_child_signal(self, name: str, signal_type: type[Signal]) -> SignalBackendT:
        basename, number = _strip_number_from_string(name)
        if backend := self._signal_backends.pop(name, None):
            # We made it above
            expected_signal_type = type(self._children[name])
        else:
            # We need to make a new one
            backend = self._signal_backend_type(self.get_datatype(name))
            signal = signal_type(backend)
            if basename in self._vectors and isinstance(number, int):
                # We need to add a new entry to an existing DeviceVector
                expected_signal_type = self._vector_device_type[basename] or signal_type
                self._vectors[basename][number] = signal
            elif name not in self._children:
                # We need to add a new child to the top level Device
                expected_signal_type = signal_type
                self._children[name] = signal
            else:
                self._raise(
                    name, f"Cannot make child as it would shadow {self._children[name]}"
                )
        if signal_type is not expected_signal_type:
            self._raise(
                name,
                f"is a {signal_type.__name__} not a {expected_signal_type.__name__}",
            )
        return backend

    def make_child_device(
        self, name: str, device_type: type[Device] = Device
    ) -> DeviceBackendT:
        basename, number = _strip_number_from_string(name)
        if backend := self._device_backends.pop(name, None):
            # We made it above
            pass
        elif basename in self._vectors and isinstance(number, int):
            # We need to add a new entry to an existing DeviceVector
            vector_device_type = self._vector_device_type[basename] or device_type
            assert issubclass(
                vector_device_type, Device
            ), f"{vector_device_type} is not a Device"
            backend = self._device_backend_type(vector_device_type)
            self._vectors[basename][number] = vector_device_type(backend=backend)
        elif name not in self._children:
            # We need to add a new child to the top level Device
            backend = self._device_backend_type(device_type)
            self._children[name] = device_type(backend=backend)
        else:
            self._raise(
                name, f"Cannot make child as it would shadow {self._children[name]}"
            )
        return backend

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


class PviDeviceBackend(DeviceBackend):
    def __init__(self, device_type: type[Device], pvi_pv: str = "") -> None:
        super().__init__(device_type)
        self.pvi_pv = pvi_pv
        self._filler = DeviceFiller(
            children=self.children,
            device_type=device_type,
            signal_backend_type=PvaSignalBackend,
            device_backend_type=PviDeviceBackend,
        )

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
                    backend = self._filler.make_child_device(name)
                    backend.pvi_pv = entry["d"]
                else:
                    signal_type, read_pv, write_pv = get_signal_details(entry)
                    backend = self._filler.make_child_signal(name, signal_type)
                    backend.read_pv = read_pv
                    backend.write_pv = write_pv
            # Check that all the requested children have been created
            if unfilled := self._filler.unfilled():
                raise RuntimeError(
                    f"{self.device_type.__name__}: cannot provision {unfilled} from "
                    f"{self.pvi_pv}: {entries}"
                )
        return await super().connect(mock, timeout, force_reconnect)
