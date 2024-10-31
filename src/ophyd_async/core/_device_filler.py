from __future__ import annotations

import re
from abc import abstractmethod
from collections.abc import Callable, Iterator, Sequence
from typing import (
    Any,
    Generic,
    NewType,
    NoReturn,
    Protocol,
    TypeVar,
    get_args,
    get_type_hints,
    runtime_checkable,
)

from ._device import Device, DeviceConnector, DeviceVector
from ._signal import Signal, SignalX
from ._signal_backend import SignalBackend, SignalDatatype
from ._utils import get_origin_class

SignalBackendT = TypeVar("SignalBackendT", bound=SignalBackend)
DeviceConnectorT = TypeVar("DeviceConnectorT", bound=DeviceConnector)
# Unique name possibly with trailing understore, the attribute name on the Device
UniqueName = NewType("UniqueName", str)
# Logical name without trailing underscore, the name in the control system
LogicalName = NewType("LogicalName", str)


def _strip_number_from_string(string: str) -> tuple[str, int | None]:
    """Return ("pulse", 1) from "pulse1"."""
    match = re.match(r"(.*?)(\d*)$", string)
    assert match

    name = match.group(1)
    number = match.group(2) or None
    if number is None:
        return name, None
    else:
        return name, int(number)


def _get_datatype(annotation: Any) -> type | None:
    """Return int from SignalRW[int]."""
    args = get_args(annotation)
    if len(args) == 1 and get_origin_class(args[0]):
        return args[0]


def _logical(name: UniqueName) -> LogicalName:
    return LogicalName(name.rstrip("_"))


@runtime_checkable
class DeviceAnnotation(Protocol):
    @abstractmethod
    def __call__(self, parent: Device, child: Device): ...


class DeviceFiller(Generic[SignalBackendT, DeviceConnectorT]):
    def __init__(
        self,
        device: Device,
        signal_backend_factory: Callable[[type[SignalDatatype] | None], SignalBackendT],
        device_connector_factory: Callable[[], DeviceConnectorT],
    ):
        self._device = device
        self._signal_backend_factory = signal_backend_factory
        self._device_connector_factory = device_connector_factory
        # Annotations stored ready for the creation phase
        self._uncreated_signals: dict[UniqueName, type[Signal]] = {}
        self._uncreated_devices: dict[UniqueName, type[Device]] = {}
        self._extras: dict[UniqueName, Sequence[Any]] = {}
        self._signal_datatype: dict[LogicalName, type | None] = {}
        self._vector_device_type: dict[LogicalName, type[Device] | None] = {}
        # Backends and Connectors stored ready for the connection phase
        self._unfilled_backends: dict[
            LogicalName, tuple[SignalBackendT, type[Signal]]
        ] = {}
        self._unfilled_connectors: dict[LogicalName, DeviceConnectorT] = {}
        # Once they are filled they go here in case we reconnect
        self._filled_backends: dict[
            LogicalName, tuple[SignalBackendT, type[Signal]]
        ] = {}
        self._filled_connectors: dict[LogicalName, DeviceConnectorT] = {}
        self._scan_for_annotations()

    def _raise(self, name: str, error: str) -> NoReturn:
        raise TypeError(f"{type(self._device).__name__}.{name}: {error}")

    def _store_signal_datatype(self, name: UniqueName, annotation: Any):
        origin = get_origin_class(annotation)
        datatype = _get_datatype(annotation)
        if origin == SignalX:
            # SignalX doesn't need datatype
            self._signal_datatype[_logical(name)] = None
        elif origin and issubclass(origin, Signal) and datatype:
            # All other Signals need one
            self._signal_datatype[_logical(name)] = datatype
        else:
            # Not recognized
            self._raise(
                name,
                f"Expected SignalX or SignalR/W/RW[type], got {annotation}",
            )

    def _scan_for_annotations(self):
        # Get type hints on the class, not the instance
        # https://github.com/python/cpython/issues/124840
        cls = type(self._device)
        # Get hints without Annotated for determining types
        hints = get_type_hints(cls)
        # Get hints with Annotated for wrapping signals and backends
        extra_hints = get_type_hints(cls, include_extras=True)
        for attr_name, annotation in hints.items():
            name = UniqueName(attr_name)
            origin = get_origin_class(annotation)
            if (
                name == "parent"
                or name.startswith("_")
                or not origin
                or not issubclass(origin, Device)
            ):
                # Ignore any child that is not a public Device
                continue
            self._extras[name] = getattr(extra_hints[attr_name], "__metadata__", ())
            if issubclass(origin, Signal):
                self._store_signal_datatype(name, annotation)
                self._uncreated_signals[name] = origin
            elif origin == DeviceVector:
                child_type = _get_datatype(annotation)
                child_origin = get_origin_class(child_type)
                if child_origin is None or not issubclass(child_origin, Device):
                    self._raise(
                        name,
                        f"Expected DeviceVector[SomeDevice], got {annotation}",
                    )
                if issubclass(child_origin, Signal):
                    self._store_signal_datatype(name, child_type)
                self._vector_device_type[_logical(name)] = child_origin
                setattr(self._device, name, DeviceVector({}))
            else:
                self._uncreated_devices[name] = origin

    def check_created(self):
        uncreated = sorted(set(self._uncreated_signals).union(self._uncreated_devices))
        if uncreated:
            raise RuntimeError(
                f"{self._device.name}: {uncreated} have not been created yet"
            )

    def create_signals_from_annotations(
        self,
        filled=True,
    ) -> Iterator[tuple[SignalBackendT, list[Any]]]:
        for name in list(self._uncreated_signals):
            child_type = self._uncreated_signals.pop(name)
            backend = self._signal_backend_factory(
                self._signal_datatype[_logical(name)]
            )
            extras = list(self._extras[name])
            yield backend, extras
            signal = child_type(backend)
            for anno in extras:
                assert isinstance(anno, DeviceAnnotation), anno
                anno(self._device, signal)
            setattr(self._device, name, signal)
            dest = self._filled_backends if filled else self._unfilled_backends
            dest[_logical(name)] = (backend, child_type)

    def create_devices_from_annotations(
        self,
        filled=True,
    ) -> Iterator[tuple[DeviceConnectorT, list[Any]]]:
        for name in list(self._uncreated_devices):
            child_type = self._uncreated_devices.pop(name)
            connector = self._device_connector_factory()
            extras = list(self._extras[name])
            yield connector, extras
            device = child_type(connector=connector)
            for anno in extras:
                assert isinstance(anno, DeviceAnnotation), anno
                anno(self._device, device)
            setattr(self._device, name, device)
            dest = self._filled_connectors if filled else self._unfilled_connectors
            dest[_logical(name)] = connector

    def create_device_vector_entries_to_mock(self, num: int):
        for basename, cls in self._vector_device_type.items():
            assert cls, "Shouldn't happen"
            for i in range(num):
                name = f"{basename}{i + 1}"
                if issubclass(cls, Signal):
                    self.fill_child_signal(name, cls)
                elif issubclass(cls, Device):
                    self.fill_child_device(name, cls)
                else:
                    self._raise(name, f"Can't make {cls}")

    def check_filled(self, source: str):
        unfilled = sorted(set(self._unfilled_connectors).union(self._unfilled_backends))
        if unfilled:
            raise RuntimeError(
                f"{self._device.name}: cannot provision {unfilled} from {source}"
            )

    def ensure_device_vectors(self, names: list[str]):
        basenames: dict[LogicalName, set[int]] = {}
        for name in names:
            basename, number = _strip_number_from_string(name)
            if number is not None:
                basenames.setdefault(LogicalName(basename), set()).add(number)
        for basename, numbers in basenames.items():
            # If contiguous numbers starting at 1 then it's a device vector
            length = len(numbers)
            if (
                length > 1
                and numbers == set(range(1, length + 1))
                and basename not in self._vector_device_type
            ):
                # We have no type hints, so use whatever we are told
                self._vector_device_type[basename] = None
                if hasattr(self._device, basename):
                    self._raise(
                        basename,
                        "Cannot make child as it would shadow "
                        f"{getattr(self._device, basename)}",
                    )
                setattr(self._device, basename, DeviceVector({}))

    def fill_child_signal(self, name: str, signal_type: type[Signal]) -> SignalBackendT:
        basename, number = _strip_number_from_string(name)
        child = getattr(self._device, name, None)
        if name in self._unfilled_backends:
            # We made it above
            backend, expected_signal_type = self._unfilled_backends.pop(name)
            self._filled_backends[name] = backend, expected_signal_type
        elif name in self._filled_backends:
            # We made it and filled it so return for validation
            backend, expected_signal_type = self._filled_backends[name]
        elif basename in self._vector_device_type and isinstance(number, int):
            # We need to add a new entry to an existing DeviceVector
            backend = self._signal_backend_factory(self._signal_datatype[basename])
            expected_signal_type = self._vector_device_type[basename] or signal_type
            getattr(self._device, basename)[number] = signal_type(backend)
        elif child is None:
            # We need to add a new child to the top level Device
            backend = self._signal_backend_factory(None)
            expected_signal_type = signal_type
            setattr(self._device, name, signal_type(backend))
        else:
            self._raise(name, f"Cannot make child as it would shadow {child}")
        if signal_type is not expected_signal_type:
            self._raise(
                name,
                f"is a {signal_type.__name__} not a {expected_signal_type.__name__}",
            )
        return backend

    def fill_child_device(
        self, name: str, device_type: type[Device] = Device
    ) -> DeviceConnectorT:
        basename, number = _strip_number_from_string(name)
        child = getattr(self._device, name, None)
        if name in self._unfilled_connectors:
            # We made it above
            connector = self._unfilled_connectors.pop(name)
            self._filled_connectors[name] = connector
        elif name in self._filled_backends:
            # We made it and filled it so return for validation
            connector = self._filled_connectors[name]
        elif basename in self._vector_device_type and isinstance(number, int):
            # We need to add a new entry to an existing DeviceVector
            vector_device_type = self._vector_device_type[basename] or device_type
            assert issubclass(
                vector_device_type, Device
            ), f"{vector_device_type} is not a Device"
            connector = self._device_connector_factory()
            getattr(self._device, basename)[number] = vector_device_type(
                connector=connector
            )
        elif child is None:
            # We need to add a new child to the top level Device
            connector = self._device_connector_factory()
            setattr(self._device, name, device_type(connector=connector))
        else:
            self._raise(name, f"Cannot make child as it would shadow {child}")
        return connector
