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

UniqueName = NewType("UniqueName", str)
LogicalName = NewType("LogicalName", str)


def _get_datatype(annotation: Any) -> type | None:
    """Return int from SignalRW[int]."""
    args = get_args(annotation)
    if len(args) == 1 and get_origin_class(args[0]):
        return args[0]
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


class DeviceFiller(Generic[SignalBackendT, DeviceConnectorT, CommandBackendT]):
    """For filling signals, devices, and commands on introspected devices.

    :param device: The device to fill.
    :param signal_backend_factory: A callable that returns a SignalBackend.
    :param device_connector_factory: A callable that returns a DeviceConnector.
    :param command_backend_factory: An optional callable that returns a CommandBackend,
        required if the device has Command children.
    """

    def __init__(
        self,
        device: Device,
        signal_backend_factory: Callable[[type[SignalDatatype] | None], SignalBackendT],
        device_connector_factory: Callable[[], DeviceConnectorT],
        command_backend_factory: Callable[[], CommandBackendT] | None = None,
    ):
        self._device = device
        self._signal_backend_factory = signal_backend_factory
        self._device_connector_factory = device_connector_factory
        self._command_backend_factory = command_backend_factory

        # Annotations stored ready for the creation phase
        self._uncreated_signals: dict[UniqueName, type[Signal]] = {}
        self._uncreated_devices: dict[UniqueName, type[Device]] = {}
        self._uncreated_commands: dict[UniqueName, type[Command]] = {}
        self._extras: dict[UniqueName, Sequence[Any]] = {}
        self._signal_datatype: dict[LogicalName, type | None] = {}
        self._vector_device_type: dict[LogicalName, type[Device] | None] = {}
        self._optional_devices: set[str] = set()
        self.ignored_signals: set[str] = set()

        # Backends and Connectors stored ready for the connection phase
        self._unfilled_backends: dict[
            LogicalName, tuple[SignalBackendT, type[Signal]]
        ] = {}
        self._unfilled_connectors: dict[LogicalName, DeviceConnectorT] = {}
        self._unfilled_command_backends: dict[
            LogicalName, tuple[CommandBackendT, type[Command]]
        ] = {}

        # Once they are filled they go here in case we reconnect
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

    def _store_signal_datatype(self, name: UniqueName, annotation: Any):
        origin = get_origin_class(annotation)
        datatype = _get_datatype(annotation)
        if origin == SignalX:
            self._signal_datatype[_logical(name)] = None
        elif origin and issubclass(origin, Signal) and datatype:
            self._signal_datatype[_logical(name)] = datatype
        else:
            self._raise(
                name,
                f"Expected SignalX or SignalR/W/RW[type], got {annotation}",
            )

    def _scan_for_annotations(self):
        cls = type(self._device)
        hints = cached_get_type_hints(cls)
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
                self._optional_devices.add(name)
                (annotation,) = [x for x in args if x is not types.NoneType]
                origin = get_origin_class(annotation)

            if (
                name == "parent"
                or name.startswith("_")
                or not origin
                or not issubclass(origin, Device)
            ):
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
            elif issubclass(origin, Command):
                # Command is a Device subclass — handle it before the generic Device branch
                self._uncreated_commands[name] = origin
            else:
                self._uncreated_devices[name] = origin

    # -------------------------------------------------------------------------
    # check_created / check_filled
    # -------------------------------------------------------------------------

    def check_created(self):
        """Check that all Signals, Devices, and Commands declared in annotations
        are created."""
        uncreated = sorted(
            set(self._uncreated_signals)
            .union(self._uncreated_devices)
            .union(self._uncreated_commands)
        )
        if uncreated:
            raise RuntimeError(
                f"{self._device.name}: {uncreated} have not been created yet"
            )

    def check_filled(self, source: str):
        """Check that all the created Signals, Devices, and Commands are filled."""
        unfilled = (
            set(self._unfilled_connectors)
            .union(self._unfilled_backends)
            .union(self._unfilled_command_backends)
        )
        unfilled_optional = sorted(unfilled.intersection(self._optional_devices))
        for name in unfilled_optional:
            setattr(self._device, name, None)
        required = sorted(unfilled.difference(unfilled_optional))
        if required:
            raise RuntimeError(
                f"{self._device.name}: cannot provision {required} from {source}"
            )

    # -------------------------------------------------------------------------
    # create_* from annotations
    # -------------------------------------------------------------------------

    def create_signals_from_annotations(
        self,
        filled=True,
    ) -> Iterator[tuple[SignalBackendT, list[Any]]]:
        """Create all Signals from annotations.

        :param filled: If True the Signals are considered already filled.
        :yields: ``(backend, extras)``
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
        """Create all child Devices (non-Command) from annotations.

        :param filled: If True the Devices are considered already filled.
        :yields: ``(connector, extras)``
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
            backend = self._command_backend_factory()
            extras = list(self._extras[name])
            yield backend, extras
            command = child_type(backend)
            for anno in extras:
                device_annotation = _check_device_annotation(annotation=anno)
                device_annotation(self._device, command)
            setattr(self._device, name, command)
            dest = (
                self._filled_command_backends if filled else self._unfilled_command_backends
            )
            dest[_logical(name)] = (backend, child_type)

    # -------------------------------------------------------------------------
    # DeviceVector mock helpers
    # -------------------------------------------------------------------------

    def create_device_vector_entries_to_mock(self, num: int):
        """Create *num* entries for each ``DeviceVector`` (used in mock mode)."""
        for name, cls in self._vector_device_type.items():
            if not cls:
                msg = "Malformed device vector"
                raise TypeError(msg)
            for i in range(1, num + 1):
                if issubclass(cls, Signal):
                    self.fill_child_signal(name, cls, i)
                elif issubclass(cls, Command):
                    self.fill_child_command(name, cls, i)
                elif issubclass(cls, Device):
                    self.fill_child_device(name, cls, i)
                else:
                    self._raise(name, f"Can't make {cls}")

    # -------------------------------------------------------------------------
    # fill_child_* helpers
    # -------------------------------------------------------------------------

    def _ensure_device_vector(self, name: LogicalName) -> DeviceVector:
        if not hasattr(self._device, name):
            self._vector_device_type[name] = None
            setattr(self._device, name, DeviceVector({}))
        vector = getattr(self._device, name)
        if not isinstance(vector, DeviceVector):
            self._raise(name, f"Expected DeviceVector, got {vector}")
        return vector

    def fill_child_signal(
        self,
        name: str,
        signal_type: type[Signal],
        vector_index: int | None = None,
    ) -> SignalBackendT:
        """Mark a Signal as filled and return its backend.

        :param name: Logical name (without trailing underscore).
        :param signal_type: One of ``SignalR``, ``SignalW``, ``SignalRW``, ``SignalX``.
        :param vector_index: Index within a ``DeviceVector``, if applicable.
        :return: The ``SignalBackend`` for the filled Signal.
        """
        name = cast(LogicalName, name)
        if name in self._unfilled_backends:
            backend, expected_signal_type = self._unfilled_backends.pop(name)
            self._filled_backends[name] = backend, expected_signal_type
        elif name in self._filled_backends:
            backend, expected_signal_type = self._filled_backends[name]
        elif vector_index:
            vector = self._ensure_device_vector(name)
            backend = self._signal_backend_factory(self._signal_datatype.get(name))
            expected_signal_type = self._vector_device_type[name] or signal_type
            vector[vector_index] = signal_type(backend)
        elif child := getattr(self._device, name, None):
            self._raise(name, f"Cannot make child as it would shadow {child}")
        else:
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
        device_type: type[Device] = Device,
        vector_index: int | None = None,
    ) -> DeviceConnectorT:
        """Mark a Device as filled and return its connector.

        :param name: Logical name (without trailing underscore).
        :param device_type: The ``Device`` subclass to create.
        :param vector_index: Index within a ``DeviceVector``, if applicable.
        :return: The ``DeviceConnector`` for the filled Device.
        """
        name = cast(LogicalName, name)
        if name in self._unfilled_connectors:
            connector = self._unfilled_connectors.pop(name)
            self._filled_connectors[name] = connector
        elif name in self._filled_connectors:
            connector = self._filled_connectors[name]
        elif vector_index:
            vector = self._ensure_device_vector(name)
            vector_device_type = self._vector_device_type[name] or device_type
            if not issubclass(vector_device_type, Device):
                msg = f"{vector_device_type} is not a Device"
                raise TypeError(msg)
            connector = self._device_connector_factory()
            vector[vector_index] = vector_device_type(connector=connector)
        elif child := getattr(self._device, name, None):
            self._raise(name, f"Cannot make child as it would shadow {child}")
        else:
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
        if name in self._unfilled_command_backends:
            backend, expected_command_type = self._unfilled_command_backends.pop(name)
            self._filled_command_backends[name] = backend, expected_command_type
        elif name in self._filled_command_backends:
            backend, expected_command_type = self._filled_command_backends[name]
        elif vector_index:
            vector = self._ensure_device_vector(name)
            vector_command_type = self._vector_device_type[name] or command_type
            if not issubclass(vector_command_type, Command):
                msg = f"{vector_command_type} is not a Command"
                raise TypeError(msg)
            backend = self._command_backend_factory()
            expected_command_type = vector_command_type
            vector[vector_index] = vector_command_type(backend)
        elif child := getattr(self._device, name, None):
            self._raise(name, f"Cannot make child as it would shadow {child}")
        else:
            backend = self._command_backend_factory()
            expected_command_type = command_type
            setattr(self._device, name, command_type(backend))
        if command_type is not expected_command_type:
            self._raise(
                name,
                f"is a {command_type.__name__} not a {expected_command_type.__name__}",
            )
        return backend