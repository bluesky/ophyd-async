from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Iterator, Mapping, MutableMapping
from functools import cached_property
from logging import LoggerAdapter, getLogger
from typing import Any, Generic, TypeVar
from unittest.mock import Mock

from bluesky.protocols import HasName

from ._utils import (
    DEFAULT_TIMEOUT,
    NotConnectedError,
    error_if_none,
    wait_for_connection,
)

DeviceT = TypeVar("DeviceT", bound="Device")

DEVICE_RESERVED_ATTRS = {
    "name",
    "collect_asset_docs",
    "get_index",
    "read_configuration",
    "describe_configuration",
    "trigger",
    "prepare",
    "read",
    "describe",
    "describe_collect",
    "collect",
    "collect_pages",
    "set",
    "locate",
    "kickoff",
    "complete",
    "stage",
    "unstage",
    "pause",
    "resume",
    "stop",
    "subscribe",
    "clear_sub",
    "check_value",
    "hints",
}


def _reserved_attrs_allowed() -> bool:
    # Opt-out for the reserved-name check, mainly so downstream test suites that
    # mock protocol methods (e.g. `device.set = AsyncMock()`) can be flipped back
    # on without editing every call site. Read from the environment each time so a
    # test can toggle it; only reached when a reserved name is actually set, so it
    # never touches the hot path. Prefer set_mock_attr() for a single override.
    return os.environ.get("OPHYD_ASYNC_ALLOW_RESERVED_ATTRS", "NO").upper() == "YES"


class DeviceMock(Generic[DeviceT]):
    """A lazily created Mock to be used when connecting in mock mode.

    Creating Mocks is reasonably expensive when each Device (and Signal)
    requires its own, and the tree is only used when ``Signal.set()`` is
    called. This class allows a tree of lazily connected Mocks to be
    constructed so that when the leaf is created, so are its parents.
    Any calls to the child are then accessible from the parent mock.

    Subclasses can override the `connect()` method to inject custom logic
    when mock devices are connected.

    ```python
    >>> parent = DeviceMock()
    >>> child = DeviceMock(name="child", parent=parent)
    >>> child_mock = child()
    >>> child_mock()  # doctest: +ELLIPSIS
    <Mock name='mock.child()' id='...'>
    >>> parent_mock = parent()
    >>> parent_mock.mock_calls
    [call.child()]

    ```
    """

    def __init__(
        self,
        name: str = "",
        parent: DeviceMock | None = None,
        mocked: bool = True,
        *,
        mock_types: Mapping[type[Device], bool | type[DeviceMock]] | None = None,
    ) -> None:
        """Create a DeviceMock.

        :param name: The name of the Device within its parent.
        :param parent: The DeviceMock of the parent Device.
        :param mocked:
            Whether the Device is mocked. A real Device still holds a DeviceMock,
            so the mocks of its mocked children nest under it.
        :param mock_types:
            The mock choice for each Device type in the tree below this one, as
            passed to [](#init_devices). Children not matched by any entry
            follow `mocked`.
        """
        self.mocked = mocked
        self.name = name
        self.parent = parent
        self.mock_types = mock_types or {}
        self._mock: Mock | None = None

    def __call__(self) -> Mock:
        if self._mock is None:
            self._mock = Mock(spec=object)
            if self.parent is not None:
                self.parent().attach_mock(self._mock, self.name)
        return self._mock

    async def connect(self, device: DeviceT) -> None:
        """Will be called when the device is connected in mock mode.

        This allows mock values to be set and callbacks to be added
        to the mock device so it behaves more like the real device.
        """


def _mocked_and_class(
    device: Device,
    mocked: bool,
    mock_types: Mapping[type[Device], bool | type[DeviceMock]],
) -> tuple[bool, type[DeviceMock]]:
    # Default mock class, and whether we are mocked is inherited from parent
    mock_class = device._mock_class  # noqa: SLF001
    # The nearest class in the MRO decides if we override
    for cls in type(device).__mro__:
        if cls in mock_types:
            choice = mock_types[cls]
            if isinstance(choice, bool):
                # Presence tells us if we should be mocked
                return choice, mock_class
            else:
                # Presence in dict says we should be mocked with this cls
                return True, choice
    # Fallthrough means inherit from parent
    return mocked, mock_class


def _without_device_entry(
    mock_types: Mapping[type[Device], bool | type[DeviceMock]],
) -> dict[type[Device], bool | type[DeviceMock]]:
    # The entry under Device is only a default for the first level of lookup
    return {cls: choice for cls, choice in mock_types.items() if cls is not Device}


def _make_mock(
    device: Device,
    name: str,
    parent: DeviceMock,
) -> DeviceMock:
    mocked, mock_class = _mocked_and_class(device, parent.mocked, parent.mock_types)
    return mock_class(
        name, parent, mocked, mock_types=_without_device_entry(parent.mock_types)
    )


async def _connect_serially(coros: Mapping[str, Awaitable[None]]) -> None:
    exceptions: dict[str, Exception] = {}
    for name, coro in coros.items():
        try:
            await coro
        except Exception as exc:
            exceptions[name] = exc
    if exceptions:
        raise NotConnectedError.with_other_exceptions_logged(exceptions)


class DeviceConnector:
    """Defines how a `Device` should be connected and type hints processed."""

    def create_children_from_annotations(self, device: Device):
        """Use when children can be created from introspecting the hardware.

        Some control systems allow introspection of a device to determine what
        children it has. To allow this to work nicely with typing we add these
        hints to the Device like so::

            my_signal: SignalRW[int]
            my_device: MyDevice

        This method will be run during `Device.__init__`, and is responsible
        for turning all of those type hints into real Signal and Device instances.

        Subsequent runs of this function should do nothing, to allow it to be
        called early in Devices that need to pass references to their children
        during `__init__`.
        """

    async def connect(
        self,
        device: Device,
        mock: DeviceMock,
        timeout: float,
        force_reconnect: bool,
    ):
        """Use during [](#Device.connect) to connect the Device and its children.

        It is called on every connect that is not cached. It connects the children,
        each with the DeviceMock made for it from `mock`, and with `timeout` and
        `force_reconnect`: in parallel, or serially when `mock` leaves nothing real
        below `device`. Overrides connect the Device itself as `mock.mocked` says,
        then call this.

        :param device: The Device being connected.
        :param mock: The DeviceMock for `device`.
        :param timeout: Time to wait before failing with a TimeoutError.
        :param force_reconnect: If True, connect the children even if their last
            connect is cached. [](#Device.connect) always passes True.
        """
        coros = {
            name: child.connect(
                mock=_make_mock(child, name, mock),
                timeout=timeout,
                force_reconnect=force_reconnect,
            )
            for name, child in device.children()
        }
        nothing_real_below = mock.mocked and False not in mock.mock_types.values()
        if nothing_real_below:
            # A Task per child is slow, and there is nothing real to wait for
            await _connect_serially(coros)
        else:
            await wait_for_connection(**coros)


def _fail_if_overwriting_parent(self: Device, name: str, value: Any):
    if self.parent not in (value, None):
        raise TypeError(
            f"Cannot set the parent of {self} to be {value}: "
            f"it is already a child of {self.parent}"
        )
    object.__setattr__(self, name, value)


def _set_device_child(self: Device, name: str, value: Device | None):
    if value is None:
        # Remove optional devices that have resolved to None
        self._child_devices.pop(name, None)
    else:
        value.parent = self
        self._child_devices[name] = value
        # And if the name is set, then set the name of all children,
        # including the child
        if self._name:
            self.set_name(self._name)
    object.__setattr__(self, name, value)


class Device(HasName):
    """Common base class for all Ophyd Async Devices.

    :param name: Optional name of the Device
    :param connector: Optional DeviceConnector instance to use at connect()
    """

    parent: Device | None = None
    """The parent Device if it exists"""
    _name: str = ""
    # The mock class to be used if we connect in mock mode
    _mock_class: type[DeviceMock] = DeviceMock
    # The DeviceMock of the last successful connect, mocked or not
    _mock: DeviceMock | None = None
    # The separator to use when making child names
    _child_name_separator: str = "-"
    # Methods to call on setattr
    _setattr_methods: dict[str, Callable[[Device, str, Any], None]]

    def __new__(cls, *args, **kwargs):
        self = super().__new__(cls)
        # These are guaranteed not to be devices, so don't check them
        setattr_methods = dict.fromkeys(_not_device_attrs, object.__setattr__) | {
            # parent needs special handling
            "parent": _fail_if_overwriting_parent,
        }
        # Assign _setattr_methods in __new__ instead of __init__,
        # as this is called before any __setattr__ calls are made
        object.__setattr__(self, "_setattr_methods", setattr_methods)
        return self

    def __init__(
        self, name: str = "", connector: DeviceConnector | None = None
    ) -> None:
        self._connector = connector or DeviceConnector()
        self._connector.create_children_from_annotations(self)
        if name:
            self.set_name(name)

    @property
    def name(self) -> str:
        """The name of the Device."""
        return self._name

    @cached_property
    def _child_devices(self) -> dict[str, Device]:
        return {}

    def children(self) -> Iterator[tuple[str, Device]]:
        """For each attribute that is a Device, yield the name and Device.

        :yields: `(attr_name, attr)` for each child attribute that is a Device.
        """
        yield from self._child_devices.items()

    @cached_property
    def log(self) -> LoggerAdapter:
        """A logger configured with the device name."""
        return LoggerAdapter(
            getLogger("ophyd_async.devices"), {"ophyd_async_device_name": self.name}
        )

    def set_name(self, name: str, *, child_name_separator: str | None = None) -> None:
        """Set `self.name=name` and each `self.child.name=name+"-child"`.

        :param name: New name to set.
        :param child_name_separator:
            Use this as a separator instead of "-". Use "_" instead to make the
            same names as the equivalent ophyd sync device.
        """
        self._name = name
        if child_name_separator:
            self._child_name_separator = child_name_separator
        # Ensure logger is recreated after a name change
        if "log" in self.__dict__:
            del self.log
        for attr_name, child in self.children():
            child_name = (
                f"{self.name}{self._child_name_separator}{attr_name}"
                if self.name
                else ""
            )
            child.set_name(child_name, child_name_separator=self._child_name_separator)

    def __setattr__(self, name: str, value: Any) -> None:
        # Bear in mind that this function is called *a lot*, so
        # we need to make sure nothing expensive happens in it, hence the
        # dictionary of setattr functions
        func = self._setattr_methods.get(name, None)
        if func is None:
            if name in DEVICE_RESERVED_ATTRS and not _reserved_attrs_allowed():
                raise NameError(
                    f"`{name}` is used in one of the bluesky protocols. "
                    f"Please use `{name}_` instead. To override this attribute in a "
                    f"test (e.g. with a mock) use ophyd_async.testing.set_mock_attr, "
                    f"or set OPHYD_ASYNC_ALLOW_RESERVED_ATTRS=YES to disable this "
                    f"check entirely."
                )
            # First encounter, so assign correct
            # __setattr__ method depending on `value` type
            if isinstance(value, Device):
                func = _set_device_child
            else:
                func = object.__setattr__
            self._setattr_methods[name] = func
        # Dispatch the correct __setattr__ method
        func(self, name, value)

    async def connect(
        self,
        mock: bool | DeviceMock = False,
        timeout: float = DEFAULT_TIMEOUT,
        force_reconnect: bool = False,
    ) -> None:
        """Connect the device and all child devices.

        A connect is cached: if the last connect succeeded, a later call with the
        same mock choice (the [](#DeviceMock) class, `mocked` and `mock_types`)
        returns without touching the children. A connect that is not cached
        connects everything below this Device again. Contains a timeout that gets
        propagated to child.connect methods.

        :param mock:
            `False` connects for real, `True` mocks this Device and everything
            below it with their default [](#DeviceMock). A [](#DeviceMock)
            instance connects this Device as its `mocked` says, and its
            `mock_types` choose for the children, see [](#init_devices). An entry
            under `Device` is the default for its direct children only. Every
            connected Device holds its DeviceMock, and the mocks of mocked
            children nest under their parent's, see [](#get_mock).
            Calling this directly on a child with a different mock choice from its
            last connect makes its mock a root, so re-connect from the parent
            instead.
        :param timeout: Time to wait before failing with a TimeoutError.
        :param force_reconnect:
            If True, connect this Device and everything below it even if the
            connect is cached.

        A connect that is not cached, in either mode, may drop subscriptions made
        before it, so subscribe again afterwards. In mock mode it also resets mock
        values and the Mock's call record.
        """
        connector: DeviceConnector = error_if_none(
            getattr(self, "_connector", None),
            f"{self}: doesn't have attribute `_connector`,"
            f" did you call `super().__init__` in your `__init__` method?",
        )
        if mock is False or mock is True:
            # Use the default mock class for this device and children
            new_mock = self._mock_class(mocked=mock)
        else:
            new_mock = mock
        use_previous_connect = (
            not force_reconnect
            and self._mock is not None
            and type(self._mock) is type(new_mock)
            and self._mock.mocked == new_mock.mocked
            and self._mock.mock_types == new_mock.mock_types
        )
        if not use_previous_connect:
            # Clear last connect, we'll make a new one
            self._mock = None
            await connector.connect(self, new_mock, timeout, force_reconnect=True)
            if new_mock.mocked:
                # Install mock behaviour once the connector has finished
                await new_mock.connect(self)
            # Connect succeeded, store the mock that encodes what it did
            self._mock = new_mock

    def __repr__(self) -> str:
        if self.name == "":
            return super().__repr__()
        return f'{type(self).__name__}(name="{self.name}")'

    def __str__(self) -> str:
        return repr(self)


_not_device_attrs = {
    "_name",
    "_children",
    "_connector",
    "_timeout",
    "_mock",
    "_child_name_separator",
    "_attempts",
}


class DeviceVector(MutableMapping[int, DeviceT], Device):
    """Defines a dictionary of Device children with arbitrary integer keys.

    :see-also: [](#implementing-devices) for examples of how to use this class.
    """

    def __init__(
        self,
        children: Mapping[int, DeviceT] | None = None,
        name: str = "",
        connector: DeviceConnector | None = None,
    ) -> None:
        self._children: dict[int, DeviceT] = {}
        self.update(children or {})
        super().__init__(name=name, connector=connector)

    def __getitem__(self, key: int) -> DeviceT:
        return self._children[key]

    def __setitem__(self, key: int, value: DeviceT) -> None:
        # Check the types on entry to dict to make sure we can't accidentally
        # make a non-integer named child
        if not isinstance(key, int):
            msg = f"Expected int, got {key}"
            raise TypeError(msg)
        if not isinstance(value, Device):
            msg = f"Expected Device, got {value}"
            raise TypeError(msg)
        self._children[key] = value
        value.parent = self

    def __delitem__(self, key: int) -> None:
        del self._children[key]

    def __iter__(self) -> Iterator[int]:
        yield from self._children

    def __len__(self) -> int:
        return len(self._children)

    def children(self) -> Iterator[tuple[str, Device]]:
        for key, child in self._children.items():
            yield str(key), child
        yield from super().children()

    def __hash__(self):  # to allow DeviceVector to be used as dict keys and in sets
        return hash(id(self))


class DeviceMap(MutableMapping[str, DeviceT], Device):
    """Defines a dictionary of Device children with arbitrary string keys.

    Like [](#DeviceVector) but indexed by `str` rather than `int`, for when
    sub-devices are more naturally addressed by name than by number.

    :see-also: [](#implementing-devices) for examples of how to use this class.
    """

    def __init__(
        self,
        children: Mapping[str, DeviceT] | None = None,
        name: str = "",
        connector: DeviceConnector | None = None,
    ) -> None:
        self._children: dict[str, DeviceT] = {}
        self.update(children or {})
        super().__init__(name=name, connector=connector)

    def __getitem__(self, key: str) -> DeviceT:
        return self._children[key]

    def __setitem__(self, key: str, value: DeviceT) -> None:
        # Check the types on entry to dict to make sure we can't accidentally
        # make a non-string named child
        if not isinstance(key, str):
            msg = f"Expected str, got {key}"
            raise TypeError(msg)
        if not isinstance(value, Device):
            msg = f"Expected Device, got {value}"
            raise TypeError(msg)
        self._children[key] = value
        value.parent = self

    def __setattr__(self, name: str, child: Any) -> None:
        # Child Devices must be set via `device_map[key] = child` so they get a
        # string key; setting them as attributes would give them no key.
        if name != "parent" and isinstance(child, Device):
            raise AttributeError(
                "DeviceMap can only have string named children, "
                "set via device_map[key] = child"
            )
        super().__setattr__(name, child)

    def __delitem__(self, key: str) -> None:
        del self._children[key]

    def __iter__(self) -> Iterator[str]:
        yield from self._children

    def __len__(self) -> int:
        return len(self._children)

    def children(self) -> Iterator[tuple[str, Device]]:
        # Keys are already str, so yield them directly (no str() needed)
        yield from self._children.items()
        yield from super().children()

    def __hash__(self):  # to allow DeviceMap to be used as dict keys and in sets
        return hash(id(self))


def default_mock_class(
    mock_cls: type[DeviceMock],
) -> Callable[[type[DeviceT]], type[DeviceT]]:
    """Register a DeviceMock subclass as the default mock for a Device class.

    This decorator allows automatic injection of mock logic when devices are
    connected in mock mode. The decorated DeviceMock class should override
    the `connect()` method to define custom mock behavior.

    :param mock_cls: A DeviceMock subclass to register.
    :returns: A decorator that registers the mock class for a Device subclass.
    """

    def wrapper(device_cls: type[DeviceT]) -> type[DeviceT]:
        device_cls._mock_class = mock_cls  # noqa: SLF001
        return device_cls

    return wrapper
