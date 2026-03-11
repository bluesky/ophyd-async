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

from ._command import Command, CommandBackend
from ._device import Device, DeviceConnector, DeviceVector
from ._signal import Ignore, Signal, SignalX
from ._signal_backend import SignalBackend, SignalDatatype
from ._utils import cached_get_origin, cached_get_type_hints, get_origin_class

SignalBackendT = TypeVar("SignalBackendT", bound=SignalBackend)
DeviceConnectorT = TypeVar("DeviceConnectorT", bound=DeviceConnector)
CommandBackendT = TypeVar("CommandBackendT", bound=CommandBackend)
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


def _get_command_datatype(annotation: Any) -> type | None:
    """Extract input type from Command[[type_in], type_out] annotations."""
    args = get_args(annotation)
    return args[1] if len(args) == 2 else None


def _get_device_vector_child_datatype(vector: Device | type[Device]) -> type | None:
    # If passed a Device, try to get the original class
    # extracting DeviceVector[SomeDevice] from a <DeviceVector>
    if generic_class := getattr(vector, "__orig_class__", None):
        # Type hinted DeviceVector
        # e.g., DeviceVector[SomeDevice]
        return _get_datatype(generic_class)
    else:
        # Sub class of type hinted DeviceVector
        # We must extract the original base, which we can do from a type or cls
        # e.g., instance of `class CustomVector(DeviceVector[SomeDevice])`
        for base in getattr(vector, "__orig_bases__", ()):
            origin = get_origin_class(base)
            if origin is DeviceVector:
                return _get_datatype(base)


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
        command_backend_factory: Callable[
            [type[SignalDatatype] | None], CommandBackendT
        ]
        | None = None,
    ):
        self._device = device
        self._signal_backend_factory = signal_backend_factory
        self._device_connector_factory = device_connector_factory
        self._command_backend_factory = command_backend_factory
        # Annotations stored ready for the creation phase
        self._uncreated_signals: dict[UniqueName, type[Signal]] = {}
        self._uncreated_commands: dict[UniqueName, type[Command]] = {}
        self._uncreated_devices: dict[UniqueName, type[Device] | DeviceFactory] = {}
        self._extras: dict[UniqueName, Sequence[Any]] = {}
        self._signal_datatype: dict[LogicalName, type | None] = {}
        self._command_datatype: dict[LogicalName, type | None] = {}
        self._vector_device_type: dict[LogicalName, type[Device] | None] = {}
        self._optional_devices: set[str] = set()
        self.ignored_signals: set[str] = set()
        # Backends and Connectors stored ready for the connection phase
        self._unfilled_backends: dict[
            LogicalName, tuple[SignalBackendT, type[Signal]]
        ] = {}
        self._unfilled_connectors: dict[LogicalName, DeviceConnectorT] = {}
        # Once they are filled they go here in case we reconnect
        self._unfilled_command_backends: dict[
            LogicalName, tuple[CommandBackendT, type[Command]]
        ] = {}
        self._filled_backends: dict[
            LogicalName, tuple[SignalBackendT, type[Signal]]
        ] = {}
        self._filled_connectors: dict[LogicalName, DeviceConnectorT] = {}
        self._filled_command_backends: dict[
            LogicalName, tuple[CommandBackendT, type[Command]]
        ] = {}
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

    def _store_signal_datatype(self, name: UniqueName, annotation: Any):
        datatype = self._validate_signal_datatype(name, annotation)
        self._signal_datatype[_logical(name)] = datatype

    def _store_command_datatype(self, name: UniqueName, annotation: Any):
        origin = get_origin_class(annotation)
        datatype = _get_command_datatype(annotation)
        print(f"origin: {origin}, datatype: {datatype}")
        if origin and issubclass(origin, Command):
            self._command_datatype[_logical(name)] = datatype
        else:
            self._raise(
                name,
                f"Expected Command or Command[[type], type], got {annotation}",
            )

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
            elif issubclass(origin, Command):
                self._store_command_datatype(name, annotation)
                self._uncreated_commands[name] = origin
            # We either have an annotation of a Device, or we have a generic alias of
            # a DeviceVector (i.e., DeviceVector[SomeDevice]), which must be callable
            # and returns a DeviceVector.
            elif (isinstance(annotation, type) and issubclass(annotation, Device)) or (
                    isinstance(annotation, types.GenericAlias) and callable(annotation)
            ):
                # Check for DeviceVector generic alias type hint
                # If this is a plain `type`, then _get_datatype will return None
                if vector_child_class := _get_datatype(annotation):
                    # Get the origin class of the type hint
                    child_origin = get_origin_class(vector_child_class)
                    if child_origin and issubclass(child_origin, Signal):
                        # This is a DeviceVector of Signals, so validate hint
                        # i.e., Check that Signal hint contains datatype
                        self._validate_signal_datatype(name, vector_child_class)
                # We may have a sub-class of DeviceVector
                # If it is not a sub-class, then its a Device, so continue
                # if it is a sub-class, check for datatype, and raise if None
                elif (
                        isinstance(annotation, type)
                        and issubclass(annotation, DeviceVector)
                        and not _get_device_vector_child_datatype(annotation)
                ):
                    # DeviceVector has no type parameter
                    self._raise(
                        name, f"Expected DeviceVector[SomeDevice], got {annotation}."
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

    def create_commands_from_annotations(
        self,
        filled=True,
    ) -> Iterator[tuple[CommandBackendT, list[Any]]]:
        """Create all Command children from annotations.

        :param filled: If True the Commands are considered already filled with
            connection data.  If False then ``fill_child_command`` must be called
            before the Command can be connected.
        :yields: ``(command_backend, extras)``
            The ``CommandBackend`` created for this Command and the list of extra
            annotations that may be used to customise it.  Unhandled extras should
            be left on the list so this class can handle them (e.g.
            ``StandardReadableFormat`` instances).
        :raises RuntimeError: If no ``command_backend_factory`` was supplied at
            construction time.
        """
        if self._command_backend_factory is None:
            uncreated = sorted(self._uncreated_commands)
            if uncreated:
                raise RuntimeError(
                    f"{self._device.name}: has Command children {uncreated} but "
                    "no command_backend_factory was provided to DeviceFiller"
                )
            return

        for name in list(self._uncreated_commands):
            child_type = self._uncreated_commands.pop(name)
            backend = self._command_backend_factory(
                self._command_datatype[_logical(name)]
            )
            extras = list(self._extras[name])
            yield backend, extras
            command = child_type(backend)
            for anno in extras:
                device_annotation = _check_device_annotation(annotation=anno)
                device_annotation(self._device, command)
            setattr(self._device, name, command)
            dest = (
                self._filled_command_backends
                if filled
                else self._unfilled_command_backends
            )
            dest[_logical(name)] = (backend, child_type)

    def create_device_vector_entries_to_mock(self, num: int):
        """Create num entries for each `DeviceVector`.

        This is used when the Device is being connected in mock mode.
        """
        hinted_child_cls = _get_device_vector_child_datatype(self._device)
        if not hinted_child_cls:
            msg = "Malformed device vector"
            raise TypeError(msg)
        # Get base class for subclass checks, as
        # generic classes are not direct subclasses
        base_cls = get_origin_class(hinted_child_cls) or Device

        # Fill DeviceVector
        self.fill_child_device(self._device.name)
        # Then handle children
        for i in range(1, num + 1):
            if issubclass(base_cls, Signal):
                self.fill_child_signal(self._device.name, hinted_child_cls, i)
            elif issubclass(base_cls, Command):
                self.fill_child_command(self._device.name, hinted_child_cls, i)
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

    def _ensure_device_vector(self) -> DeviceVector:
        if not isinstance(self._device, DeviceVector):
            self._raise(self._device.name, f"Expected DeviceVector, got {self._device}")
        return self._device

    def fill_child_signal(
        self,
        name: str,
        signal_type: type[Signal],
        vector_index: int | None = None,
    ) -> SignalBackendT:
        """Mark a Signal as filled, and return its backend for filling.

        :param name:
            The name without trailing underscore, the name in the control system
        :param signal_type:
            One of the types `SignalR`, `SignalW`, `SignalRW` or `SignalX`
        :param vector_index: If the child is in a `DeviceVector` then what index is it
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
        elif vector_index:
            # We need to add a new entry to a DeviceVector
            backend = self._signal_backend_factory(_get_datatype(signal_type))
            vector = self._ensure_device_vector()
            expected_signal_type = (
                _get_device_vector_child_datatype(vector) or signal_type
            )
            vector[vector_index] = signal_type(backend)
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
        device_type: type[Device | DeviceVector] = Device,
        vector_index: int | None = None,
    ) -> DeviceConnectorT:
        """Mark a Device as filled, and return its connector for filling.

        :param name:
            The name without trailing underscore, the name in the control system
        :param device_type: The `Device` subclass to be created
        :param vector_index: If the child is in a `DeviceVector` then what index is it
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
        elif vector_index is not None:
            # We need to add a new entry to a DeviceVector
            vector = self._ensure_device_vector()
            vector_device_type = (
                _get_device_vector_child_datatype(vector) or device_type
            )
            if not issubclass(vector_device_type, Device):
                # Raise if adding Non-Device to DeviceVector
                self._raise(
                    name,
                    f"Expected {type(self._device).__name__}"
                    f"[{vector_device_type.__name__}], "
                    f"but {vector_device_type} is not a subclass of `Device`",
                )
            connector = self._device_connector_factory()
            vector[vector_index] = vector_device_type(connector=connector)
        elif child := getattr(self._device, name, None):
            # There is an existing child, so raise
            self._raise(name, f"Cannot make child as it would shadow {child}")
        else:
            # We need to add a new child Device to the top level Device
            connector = self._device_connector_factory()
            setattr(self._device, name, device_type(connector=connector))
        return connector

    def fill_child_command(
        self,
        name: str,
        command_type: type[Command] = Command,
        vector_index: int | None = None,
    ) -> CommandBackendT:
        """Mark a Command as filled and return its backend.

        This version prioritizes checking _filled_command_backends before the shadowing
        check, matching the behavior of fill_child_signal.

        :param name: Logical name (without trailing underscore).
        :param command_type: The ``Command`` subclass to create.
        :param vector_index: Index within a ``DeviceVector``, if applicable.
        :return: The ``CommandBackend`` for the filled Command.
        :raises RuntimeError: If no ``command_backend_factory`` was provided.
        """
        if self._command_backend_factory is None:
            raise RuntimeError(
                f"{self._device.name}: cannot fill Command child '{name}' — "
                "no command_backend_factory was provided to DeviceFiller"
            )

        name = cast(LogicalName, name)

        # First check unfilled command backends
        if name in self._unfilled_command_backends:
            backend, expected_command_type = self._unfilled_command_backends.pop(name)
            self._filled_command_backends[name] = backend, expected_command_type

        # Then check filled command backends (this was missing in the original)
        elif name in self._filled_command_backends:
            backend, expected_command_type = self._filled_command_backends[name]

        # Handle DeviceVector case
        elif vector_index:
            vector = self._ensure_device_vector(name)
            vector_command_type = self._vector_device_type[name] or command_type
            if not issubclass(vector_command_type, Command):
                msg = f"{vector_command_type} is not a Command"
                raise TypeError(msg)
            backend = self._command_backend_factory(
                self._command_datatype[_logical(name)]
            )
            expected_command_type = vector_command_type
            vector[vector_index] = vector_command_type(backend)

        # Shadowing check moved to last position
        elif child := getattr(self._device, name, None):
            self._raise(name, f"Cannot make child as it would shadow {child}")

        # Create new command if none of the above matched
        else:
            backend = self._command_backend_factory(None)
            expected_command_type = command_type
            setattr(self._device, name, command_type(backend))

        if command_type is not expected_command_type:
            self._raise(
                name,
                f"is a {command_type.__name__} not a {expected_command_type.__name__}",
            )

        return backend
