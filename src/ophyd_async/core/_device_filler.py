from __future__ import annotations

import types
from abc import abstractmethod
from collections.abc import Callable, Iterator, Sequence
from typing import (
    Any,
    Generic,
    NewType,
    NoReturn,
    Protocol,
    TypeVar,
    Union,
    cast,
    get_args,
    runtime_checkable,
)

from ._device import Device, DeviceCollection, DeviceConnector
from ._signal import Ignore, Signal, SignalX
from ._signal_backend import SignalBackend, SignalDatatype
from ._utils import cached_get_origin, cached_get_type_hints, get_origin_class

SignalBackendT = TypeVar("SignalBackendT", bound=SignalBackend)
DeviceConnectorT = TypeVar("DeviceConnectorT", bound=DeviceConnector)
# Unique name possibly with trailing understore, the attribute name on the Device
UniqueName = NewType("UniqueName", str)
# Logical name without trailing underscore, the name in the control system
LogicalName = NewType("LogicalName", str)


class DeviceFactory(Protocol):
    def __call__(self, connector: DeviceConnector) -> Device: ...


def _get_datatype(annotation: Any) -> type | None:
    """Return int from SignalRW[int]."""
    args = get_args(annotation)
    if len(args) == 1 and get_origin_class(args[0]):
        return args[0]

    return None


def _get_device_collection_child_datatype(map: Device | type[Device]) -> type | None:
    # If passed a Device, try to get the original class
    # extracting DeviceCollection[T, SomeDevice] from a <DeviceCollection>
    if generic_class := getattr(map, "__orig_class__", None):
        # Type hinted DeviceCollection
        # e.g., DeviceCollection[T, SomeDevice]
        return _get_datatype(generic_class)

    for base in getattr(map, "__orig_bases__", ()):
        # Sub class of type hinted DeviceCollection
        # We must extract the original base, which we can do from a type or cls
        # e.g., instance of `class CustomMap(DeviceCollection[T, SomeDevice])`
        origin = get_origin_class(base)
        if (
            origin is not None
            and isinstance(origin, type)
            and issubclass(origin, DeviceCollection)
        ):
            datatype = _get_datatype(base)
            if datatype is not None:
                return datatype

            datatype = _get_device_collection_child_datatype(origin)
            if datatype is not None:
                return datatype

    return None


def _logical(name: UniqueName) -> LogicalName:
    return LogicalName(name.rstrip("_"))


def _check_device_annotation(annotation: Any) -> DeviceAnnotation:
    if not isinstance(annotation, DeviceAnnotation):
        msg = f"Annotation {annotation} is not a DeviceAnnotation"
        raise TypeError(msg)
    return annotation


@runtime_checkable
class DeviceAnnotation(Protocol):
    @abstractmethod
    def __call__(self, parent: Device, child: Device): ...


class DeviceFiller(Generic[SignalBackendT, DeviceConnectorT]):
    """For filling signals on introspected devices.

    :param device: The device to fill.
    :param signal_backend_factory: A callable that returns a SignalBackend.
    :param device_connector_factory: A callable that returns a DeviceConnector.
    """

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
        self._uncreated_devices: dict[UniqueName, type[Device] | DeviceFactory] = {}
        self._extras: dict[UniqueName, Sequence[Any]] = {}
        self._signal_datatype: dict[LogicalName, type | None] = {}
        self._device_map_type: dict[LogicalName, type[Device] | None] = {}
        self._optional_devices: set[str] = set()
        self.ignored_signals: set[str] = set()
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

    def _validate_signal_datatype(
        self, name: UniqueName, annotation: Any
    ) -> type | None:
        origin = get_origin_class(annotation)
        datatype = _get_datatype(annotation)
        if not datatype and origin != SignalX:
            # Not recognized
            self._raise(
                name,
                f"Expected SignalX or SignalR/W/RW[type], got {annotation}",
            )
        return datatype

    def _store_signal_datatype(self, name: UniqueName, annotation: Any):
        datatype = self._validate_signal_datatype(name, annotation)
        self._signal_datatype[_logical(name)] = datatype

    def _scan_for_annotations(self):
        # Get type hints on the class, not the instance
        # https://github.com/python/cpython/issues/124840
        cls = type(self._device)
        # Get hints without Annotated for determining types
        hints = cached_get_type_hints(cls)
        # Get hints with Annotated for wrapping signals and backends
        extra_hints = cached_get_type_hints(cls, include_extras=True)
        for attr_name, annotation in hints.items():
            if annotation is Ignore:
                self.ignored_signals.add(attr_name)
            name = UniqueName(attr_name)
            origin = get_origin_class(annotation)
            args = get_args(annotation)

            if (
                cached_get_origin(annotation) is Union
                and types.NoneType in args
                and len(args) == 2
            ):
                # Annotation is an Union with two arguments, one of which is None
                # Make this signal an optional parameter and set origin to T
                # so the device is added to unfilled_connectors
                self._optional_devices.add(name)
                (annotation,) = [x for x in args if x is not types.NoneType]
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
            # We either have an annotation of a Device, or we have a generic alias of
            # a DeviceCollection (i.e., DeviceCollection[T, SomeDevice]), which must be
            # callable and returns a DeviceCollection.
            elif (isinstance(annotation, type) and issubclass(annotation, Device)) or (
                isinstance(annotation, types.GenericAlias) and callable(annotation)
            ):
                # Check for DeviceCollection generic alias type hint
                # If this is a plain `type`, then _get_datatype will return None
                if device_map_child_class := _get_datatype(annotation):
                    # Get the origin class of the type hint
                    child_origin = get_origin_class(device_map_child_class)
                    if child_origin and issubclass(child_origin, Signal):
                        # This is a DeviceCollection of Signals, so validate hint
                        # i.e., Check that Signal hint contains datatype
                        self._validate_signal_datatype(name, device_map_child_class)
                # We may have a sub-class of DeviceCollection
                # If it is not a sub-class, then its a Device, so continue
                # if it is a sub-class, check for datatype, and raise if None
                elif (
                    isinstance(annotation, type)
                    and issubclass(annotation, DeviceCollection)
                    and not _get_device_collection_child_datatype(annotation)
                ):
                    # DeviceCollection has no type parameter
                    self._raise(
                        name,
                        f"Expected DeviceCollection[T, SomeDevice], got {annotation}.",
                    )
                self._uncreated_devices[name] = annotation

    def check_created(self):
        """Check that all Signals and Devices declared in annotations are created."""
        uncreated = sorted(set(self._uncreated_signals).union(self._uncreated_devices))
        if uncreated:
            raise RuntimeError(
                f"{self._device.name}: {uncreated} have not been created yet"
            )

    def create_signals_from_annotations(
        self,
        filled=True,
    ) -> Iterator[tuple[SignalBackendT, list[Any]]]:
        """Create all Signals from annotations.

        :param filled:
            If True then the Signals created should be considered already filled
            with connection data. If False then `fill_child_signal` needs
            calling at device connection time before the signal can be
            connected.
        :yields: `(backend, extras)`
            The `SignalBackend` that has been created for this Signal, and the
            list of extra annotations that could be used to customize it. For
            example an `EpicsDeviceConnector` consumes `PvSuffix` extras to set the
            write_pv of the backend. Any unhandled extras should be left on the
            list so this class can handle them, e.g. `StandardReadableFormat`
            instances.
        """
        for name in list(self._uncreated_signals):
            child_type = self._uncreated_signals.pop(name)
            backend = self._signal_backend_factory(
                self._signal_datatype[_logical(name)]
            )
            extras = list(self._extras[name])
            yield backend, extras
            signal = child_type(backend)
            for anno in extras:
                device_annotation = _check_device_annotation(annotation=anno)
                device_annotation(self._device, signal)
            setattr(self._device, name, signal)
            dest = self._filled_backends if filled else self._unfilled_backends
            dest[_logical(name)] = (backend, child_type)

    def create_devices_from_annotations(
        self,
        filled=True,
    ) -> Iterator[tuple[DeviceConnectorT, list[Any]]]:
        """Create all Signals from annotations.

        :param filled:
            If True then the Devices created should be considered already filled
            with connection data. If False then `fill_child_device` needs
            calling at parent device connection time before the child Device can
            be connected.
        :yields: `(connector, extras)`
            The `DeviceConnector` that has been created for this Signal, and the list of
            extra annotations that could be used to customize it.
        """
        for name in list(self._uncreated_devices):
            child_type = self._uncreated_devices.pop(name)
            connector = self._device_connector_factory()
            extras = list(self._extras[name])
            yield connector, extras
            device = child_type(connector=connector)
            for anno in extras:
                device_annotation = _check_device_annotation(annotation=anno)
                device_annotation(self._device, device)
            setattr(self._device, name, device)
            dest = self._filled_connectors if filled else self._unfilled_connectors
            dest[_logical(name)] = connector

    def create_device_collection_entries_to_mock(self, entries: list[Any]):
        """Create num entries for each `DeviceCollection`.

        This is used when the Device is being connected in mock mode.
        """
        hinted_child_cls = _get_device_collection_child_datatype(self._device)
        if not hinted_child_cls:
            msg = "Malformed device map"
            raise TypeError(msg)
        # Get base class for subclass checks, as
        # generic classes are not direct subclasses
        base_cls = get_origin_class(hinted_child_cls) or Device

        # Fill DeviceCollection
        self.fill_child_device(self._device.name)
        # Then handle children
        for i in entries:
            if issubclass(base_cls, Signal):
                self.fill_child_signal(self._device.name, hinted_child_cls, i)
            elif issubclass(base_cls, Device):
                self.fill_child_device(self._device.name, hinted_child_cls, i)
            else:
                self._raise(self._device.name, f"Can't make {hinted_child_cls}")

    def check_filled(self, source: str):
        """Check that all the created Signals and Devices are filled.

        :param source: The source of the data that should have done the filling, for
                       reporting as an error message
        """
        unfilled = set(self._unfilled_connectors).union(self._unfilled_backends)
        unfilled_optional = sorted(unfilled.intersection(self._optional_devices))

        for name in unfilled_optional:
            setattr(self._device, name, None)

        required = sorted(unfilled.difference(unfilled_optional))

        if required:
            raise RuntimeError(
                f"{self._device.name}: cannot provision {required} from {source}"
            )

    def _ensure_device_collection(self) -> DeviceCollection:
        if not isinstance(self._device, DeviceCollection):
            self._raise(
                self._device.name, f"Expected DeviceCollection, got {self._device}"
            )
        return self._device

    def fill_child_signal(
        self,
        name: str,
        signal_type: type[Signal],
        map_key: int | str | None = None,
    ) -> SignalBackendT:
        """Mark a Signal as filled, and return its backend for filling.

        :param name:
            The name without trailing underscore, the name in the control system
        :param signal_type:
            One of the types `SignalR`, `SignalW`, `SignalRW` or `SignalX`
        :param map_key: If the child is in a `DeviceCollection` then what key is it
        :return: The SignalBackend for the filled Signal.
        """
        name = cast(LogicalName, name)
        if name in self._unfilled_backends:
            # We made it above
            backend, expected_signal_type = self._unfilled_backends.pop(name)
            self._filled_backends[name] = backend, expected_signal_type
        elif name in self._filled_backends:
            # We made it and filled it so return for validation
            backend, expected_signal_type = self._filled_backends[name]
        elif map_key:
            # We need to add a new entry to a DeviceCollection
            backend = self._signal_backend_factory(_get_datatype(signal_type))
            device_collection = self._ensure_device_collection()
            expected_signal_type = (
                _get_device_collection_child_datatype(device_collection) or signal_type
            )
            key_type = device_collection.key_type
            device_collection[key_type(map_key)] = signal_type(backend)
        elif child := getattr(self._device, name, None):
            # There is an existing child, so raise
            self._raise(name, f"Cannot make child as it would shadow {child}")
        else:
            # We need to add a new child to the top level Device
            backend = self._signal_backend_factory(None)
            expected_signal_type = signal_type
            setattr(self._device, name, signal_type(backend))
        if signal_type is not expected_signal_type:
            self._raise(
                name,
                f"is a {signal_type.__name__} not a {expected_signal_type.__name__}",
            )
        return backend

    def fill_child_device(
        self,
        name: str,
        device_type: type[Device | DeviceCollection] = Device,
        map_key: Any | None = None,
    ) -> DeviceConnectorT:
        """Mark a Device as filled, and return its connector for filling.

        :param name:
            The name without trailing underscore, the name in the control system
        :param device_type: The `Device` subclass to be created
        :param map_key: If the child is in a `DeviceCollection` then what key is it
        :return: The DeviceConnector for the filled Device.
        """
        name = cast(LogicalName, name)
        if name in self._unfilled_connectors:
            # We made it above
            connector = self._unfilled_connectors.pop(name)
            self._filled_connectors[name] = connector
        elif name in self._filled_backends:
            # We made it and filled it so return for validation
            connector = self._filled_connectors[name]
        elif map_key is not None:
            # We need to add a new entry to a DeviceCollection
            device_map = self._ensure_device_collection()
            device_map_type = (
                _get_device_collection_child_datatype(device_map) or device_type
            )
            if not issubclass(device_map_type, Device):
                # Raise if adding Non-Device to DeviceCollection
                self._raise(
                    name,
                    f"Expected {type(self._device).__name__}"
                    f"[{device_map_type.__name__}], "
                    f"but {device_map_type} is not a subclass of `Device`",
                )
            connector = self._device_connector_factory()
            device_map[map_key] = device_map_type(connector=connector)
        elif child := getattr(self._device, name, None):
            # There is an existing child, so raise
            self._raise(name, f"Cannot make child as it would shadow {child}")
        else:
            # We need to add a new child Device to the top level Device
            connector = self._device_connector_factory()
            setattr(self._device, name, device_type(connector=connector))
        return connector
