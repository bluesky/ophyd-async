from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable, Iterator, Mapping, MutableMapping
from functools import cached_property
from logging import LoggerAdapter, getLogger
from typing import Any, TypeVar

from bluesky.protocols import HasName
from bluesky.run_engine import call_in_bluesky_event_loop, in_bluesky_event_loop

from ._utils import (
    DEFAULT_TIMEOUT,
    LazyMock,
    NotConnected,
    error_if_none,
    wait_for_connection,
)


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

    async def connect_mock(self, device: Device, mock: LazyMock):
        """Use during [](#Device.connect) with `mock=True`.

        This is called when there is no cached connect done in `mock=True`
        mode. It connects the Device and all its children in mock mode.
        """
        # Connect serially, no errors to gather up as in mock mode
        exceptions: dict[str, Exception] = {}
        for name, child_device in device.children():
            try:
                await child_device.connect(mock=mock.child(name))
            except Exception as e:
                exceptions[name] = e
        if exceptions:
            raise NotConnected.with_other_exceptions_logged(exceptions)

    async def connect_real(self, device: Device, timeout: float, force_reconnect: bool):
        """Use during [](#Device.connect) with `mock=False`.

        This is called when there is no cached connect done in `mock=False`
        mode. It connects the Device and all its children in real mode in parallel.
        """
        # Connect in parallel, gathering up NotConnected errors
        coros = {
            name: child_device.connect(timeout=timeout, force_reconnect=force_reconnect)
            for name, child_device in device.children()
        }
        await wait_for_connection(**coros)


class Device(HasName):
    """Common base class for all Ophyd Async Devices.

    :param name: Optional name of the Device
    :param connector: Optional DeviceConnector instance to use at connect()
    """

    parent: Device | None = None
    """The parent Device if it exists"""
    _name: str = ""
    # None if connect hasn't started, a Task if it has
    _connect_task: asyncio.Task | None = None
    # The mock if we have connected in mock mode
    _mock: LazyMock | None = None
    # The separator to use when making child names
    _child_name_separator: str = "-"

    def __init__(
        self, name: str = "", connector: DeviceConnector | None = None
    ) -> None:
        self._connector = connector or DeviceConnector()
        self._connector.create_children_from_annotations(self)
        if name:
            self.set_name(name)

    @property
    def name(self) -> str:
        """Return the name of the Device."""
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
        """Return a logger configured with the device name."""
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
        # we need to make sure nothing expensive happens in it...
        if name == "parent":
            if self.parent not in (value, None):
                raise TypeError(
                    f"Cannot set the parent of {self} to be {value}: "
                    f"it is already a child of {self.parent}"
                )
        # ...hence not doing an isinstance check for attributes we
        # know not to be Devices
        elif name not in _not_device_attrs and isinstance(value, Device):
            value.parent = self
            self._child_devices[name] = value
            # And if the name is set, then set the name of all children,
            # including the child
            if self._name:
                self.set_name(self._name)
        # ...and avoiding the super call as we know it resolves to `object`
        return object.__setattr__(self, name, value)

    async def connect(
        self,
        mock: bool | LazyMock = False,
        timeout: float = DEFAULT_TIMEOUT,
        force_reconnect: bool = False,
    ) -> None:
        """Connect the device and all child devices.

        Successful connects will be cached so subsequent calls will return
        immediately. Contains a timeout that gets propagated to child.connect
        methods.

        :param mock:
            If True then use [](#MockSignalBackend) for all Signals. If passed a
            [](#LazyMock) then pass this down for use within the Signals,
            otherwise create one.
        :param timeout: Time to wait before failing with a TimeoutError.
        :param force_reconnect:
            If True, force a reconnect even if the last connect succeeded.
        """
        connector = error_if_none(
            getattr(self, "_connector", None),
            f"{self}: doesn't have attribute `_connector`,"
            f" did you call `super().__init__` in your `__init__` method?",
        )
        if mock:
            # Always connect in mock mode serially
            if isinstance(mock, LazyMock):
                # Use the provided mock
                self._mock = mock
            elif not self._mock:
                # Make one
                self._mock = LazyMock()
            await connector.connect_mock(self, self._mock)
        else:
            # Try to cache the connect in real mode
            can_use_previous_connect = (
                self._mock is None
                and self._connect_task
                and not (self._connect_task.done() and self._connect_task.exception())
            )
            if force_reconnect or not can_use_previous_connect:
                self._mock = None
                coro = connector.connect_real(self, timeout, force_reconnect)
                self._connect_task = asyncio.create_task(coro)
            connect_task = error_if_none(
                self._connect_task, "Connect task not created, this shouldn't happen"
            )
            # Wait for it to complete
            await connect_task


_not_device_attrs = {
    "_name",
    "_children",
    "_connector",
    "_timeout",
    "_mock",
    "_connect_task",
}


DeviceT = TypeVar("DeviceT", bound=Device)


class DeviceVector(MutableMapping[int, DeviceT], Device):
    """Defines a dictionary of Device children with arbitrary integer keys.

    :see-also: [](#implementing-devices) for examples of how to use this class.
    """

    def __init__(
        self,
        children: Mapping[int, DeviceT],
        name: str = "",
    ) -> None:
        self._children: dict[int, DeviceT] = {}
        self.update(children)
        super().__init__(name=name)

    def __setattr__(self, name: str, child: Any) -> None:
        if name != "parent" and isinstance(child, Device):
            raise AttributeError(
                "DeviceVector can only have integer named children, "
                "set via device_vector[i] = child"
            )
        super().__setattr__(name, child)

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

    def __hash__(self):  # to allow DeviceVector to be used as dict keys and in sets
        return hash(id(self))


class DeviceProcessor:
    """Sync/Async Context Manager that finds all the Devices declared within it.

    Used in `init_devices`
    """

    def __init__(self, process_devices: Callable[[dict[str, Device]], Awaitable[None]]):
        self._process_devices = process_devices
        self._locals_on_enter: dict[str, Any] = {}
        self._locals_on_exit: dict[str, Any] = {}

    def _caller_locals(self) -> dict[str, Any]:
        """Walk up until we find a stack frame that doesn't have us as self."""
        try:
            raise ValueError
        except ValueError:
            _, _, tb = sys.exc_info()
            tb = error_if_none(tb, "Can't get traceback, this shouldn't happen")

            caller_frame = tb.tb_frame
            while caller_frame.f_locals.get("self", None) is self:
                caller_frame = caller_frame.f_back
                if not caller_frame:
                    msg = (
                        "No previous frame to the one with self in it, "
                        "this shouldn't happen"
                    )
                    raise RuntimeError(  # noqa: B904
                        msg
                    )
            return caller_frame.f_locals.copy()

    def __enter__(self) -> DeviceProcessor:
        # Stash the names that were defined before we were called
        self._locals_on_enter = self._caller_locals()
        return self

    async def __aenter__(self) -> DeviceProcessor:
        return self.__enter__()

    async def __aexit__(self, type, value, traceback):
        self._locals_on_exit = self._caller_locals()
        await self._on_exit()

    def __exit__(self, type_, value, traceback):
        if in_bluesky_event_loop():
            raise RuntimeError(
                "Cannot use DeviceConnector inside a plan, instead use "
                "`yield from ophyd_async.plan_stubs.ensure_connected(device)`"
            )
        self._locals_on_exit = self._caller_locals()
        try:
            fut = call_in_bluesky_event_loop(self._on_exit())
        except RuntimeError as e:
            raise NotConnected(
                "Could not connect devices. Is the bluesky event loop running? See "
                "https://blueskyproject.io/ophyd-async/main/"
                "user/explanations/event-loop-choice.html for more info."
            ) from e
        return fut

    async def _on_exit(self) -> None:
        # Find all the devices
        devices = {
            name: obj
            for name, obj in self._locals_on_exit.items()
            if isinstance(obj, Device) and self._locals_on_enter.get(name) is not obj
        }
        # Call the provided process function on them
        await self._process_devices(devices)


def init_devices(
    set_name: bool = True,
    child_name_separator: str = "-",
    connect: bool = True,
    mock: bool = False,
    timeout: float = 10.0,
):
    """Auto initialize top level Device instances: to be used as a context manager.

    :param set_name:
        If True, call `device.set_name(variable_name)` on all Devices created
        within the context manager that have an empty `name`.
    :param child_name_separator: Separator for child names if `set_name` is True.
    :param connect:
        If True, call `device.connect(mock, timeout)` in parallel on all Devices
        created within the context manager.
    :param mock: If True, connect Signals in mock mode.
    :param timeout: How long to wait for connect before logging an exception.
    :raises RuntimeError: If used inside a plan, use [](#ensure_connected) instead.
    :raises NotConnected: If devices could not be connected.

    For example, to connect and name 2 motors in parallel:
    ```python
    [async] with init_devices():
        t1x = motor.Motor("BLxxI-MO-TABLE-01:X")
        t1y = motor.Motor("pva://BLxxI-MO-TABLE-01:Y")
        # Names and connects devices here
    assert t1x.name == "t1x"
    ```
    """

    async def process_devices(devices: dict[str, Device]):
        if set_name:
            for name, device in devices.items():
                if not device.name:
                    device.set_name(name, child_name_separator=child_name_separator)
        if connect:
            coros = {
                name: device.connect(mock, timeout) for name, device in devices.items()
            }
            await wait_for_connection(**coros)

    return DeviceProcessor(process_devices)
