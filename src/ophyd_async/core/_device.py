from __future__ import annotations

import asyncio
import sys
from abc import abstractmethod
from collections.abc import Coroutine, Iterator, Mapping, MutableMapping
from functools import cached_property
from logging import LoggerAdapter, getLogger
from typing import Any, Generic, TypeVar

from bluesky.protocols import HasName
from bluesky.run_engine import call_in_bluesky_event_loop

from ._utils import DEFAULT_TIMEOUT, NotConnected, wait_for_connection


class DeviceBackend:
    # TODO: we will add some mechanism of invalidating the cache here later
    @abstractmethod
    async def connect(
        self, mock: bool, timeout: float, force_reconnect: bool
    ) -> None: ...


DeviceBackendT = TypeVar("DeviceBackendT", bound=DeviceBackend)


class Device(HasName, Generic[DeviceBackendT]):
    """Common base class for all Ophyd Async Devices."""

    _name: str = ""
    #: The parent Device if it exists
    parent: Device | None = None

    def __init__(
        self,
        backend: DeviceBackendT,
        name: str = "",
    ) -> None:
        # None if connect hasn't started, a Task if it has
        self._connect_task: asyncio.Task | None = None
        # The value of the mock arg to connect
        self._connect_mock_arg: bool | None = None
        self._backend = backend
        self.set_name(name)

    @cached_property
    def log(self):
        return LoggerAdapter(
            getLogger("ophyd_async.devices"), {"ophyd_async_device_name": self.name}
        )

    @property
    def name(self) -> str:
        """Return the name of the Device"""
        return self._name

    def set_name(self, name: str):
        # Ensure self.log is recreated after a name change
        if hasattr(self, "log"):
            del self.log
        self._name = name

    async def connect(
        self,
        mock: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        force_reconnect: bool = False,
    ):
        """Connect self and all child Devices.

        Contains a timeout that gets propagated to child.connect methods.

        Parameters
        ----------
        mock:
            If True then use ``MockSignalBackend`` for all Signals
        timeout:
            Time to wait before failing with a TimeoutError.
        """

        # If previous connect with same args has started and not errored, can use it
        can_use_previous_connect = (
            mock is self._connect_mock_arg
            and self._connect_task
            and not (self._connect_task.done() and self._connect_task.exception())
        )
        if force_reconnect or not can_use_previous_connect:
            # Ask the backend to do a new connection
            self._connect_mock_arg = mock
            self._connect_task = asyncio.create_task(
                self._backend.connect(
                    mock=mock, timeout=timeout, force_reconnect=force_reconnect
                )
            )
        assert self._connect_task, "Connect task not created, this shouldn't happen"
        # Wait for it to complete
        await self._connect_task


DeviceT = TypeVar("DeviceT", bound=Device)


class DeviceTreeBackend(DeviceBackend):
    def __init__(self) -> None:
        self.children: dict[str, Device] = {}

    async def connect(self, mock: bool, timeout: float, force_reconnect: bool) -> None:
        coros = {
            name: child_device.connect(
                mock=mock, timeout=timeout, force_reconnect=force_reconnect
            )
            for name, child_device in self.children.items()
        }
        await wait_for_connection(**coros)


class DeviceTree(Device[DeviceTreeBackend]):
    def __init__(
        self, backend: DeviceTreeBackend | None = None, name: str = ""
    ) -> None:
        if backend is None:
            backend = DeviceTreeBackend()
        super().__init__(backend, name)

    def _set_child_name(self, child: Device, child_name: str):
        child_name = f"{self.name}-{child_name.rstrip('_')}" if self.name else ""
        child.set_name(child_name)

    def set_name(self, name: str) -> None:
        super().set_name(name)
        for child_name, child in self._backend.children.items():
            self._set_child_name(child, child_name)

    def __setattr__(self, name: str, child: Device) -> None:
        if name != "parent" and isinstance(child, Device):
            self._backend.children[name] = child
            child.parent = self
            self._set_child_name(child, name)
        else:
            super().__setattr__(name, child)

    def __getattr__(self, name: str) -> Device:
        if name == "_backend":
            raise AttributeError("Must set backend before adding Device children")
        child = self._backend.children.get(name, None)
        if child is None:
            raise AttributeError(
                f"'{type(self).__name__}' object has not attribute '{name}'"
            )
        else:
            return child


class DeviceVectorBackend(DeviceBackend, Generic[DeviceT]):
    def __init__(self) -> None:
        self.children: dict[int, DeviceT] = {}

    async def connect(self, mock: bool, timeout: float, force_reconnect: bool) -> None:
        coros = {
            str(name): child_device.connect(
                mock=mock, timeout=timeout, force_reconnect=force_reconnect
            )
            for name, child_device in self.children.items()
        }
        await wait_for_connection(**coros)


class DeviceVector(MutableMapping[int, DeviceT], Device[DeviceVectorBackend[DeviceT]]):
    """
    Defines device components with indices.

    In the below example, foos becomes a dictionary on the parent device
    at runtime, so parent.foos[2] returns a FooDevice. For example usage see
    :class:`~ophyd_async.epics.demo.DynamicSensorGroup`
    """

    def __init__(
        self,
        children: Mapping[int, DeviceT],
        name: str = "",
    ) -> None:
        super().__init__(name=name, backend=DeviceVectorBackend())
        for child_name, child in children.items():
            self[child_name] = child

    def _set_child_name(self, child: Device, key: int):
        child_name = f"{self.name}-{key}" if self.name else ""
        child.set_name(child_name)

    def set_name(self, name: str) -> None:
        super().set_name(name)
        for child_name, child in self._backend.children.items():
            self._set_child_name(child, child_name)

    def __getitem__(self, key: int) -> DeviceT:
        assert isinstance(key, int), f"Expected int, got {key}"
        return self._backend.children[key]

    def __setitem__(self, key: int, value: DeviceT) -> None:
        assert isinstance(key, int), f"Expected int, got {key}"
        assert isinstance(value, Device), f"Expected Device, got {value}"
        self._backend.children[key] = value
        value.parent = self
        self._set_child_name(value, key)

    def __delitem__(self, key: int) -> None:
        assert isinstance(key, int), f"Expected int, got {key}"
        del self._backend.children[key]

    def __iter__(self) -> Iterator[int]:
        yield from self._backend.children

    def __len__(self) -> int:
        return len(self._backend.children)


class DeviceCollector:
    """Collector of top level Device instances to be used as a context manager

    Parameters
    ----------
    set_name:
        If True, call ``device.set_name(variable_name)`` on all collected
        Devices
    connect:
        If True, call ``device.connect(mock)`` in parallel on all
        collected Devices
    mock:
        If True, connect Signals in simulation mode
    timeout:
        How long to wait for connect before logging an exception

    Notes
    -----
    Example usage::

        [async] with DeviceCollector():
            t1x = motor.Motor("BLxxI-MO-TABLE-01:X")
            t1y = motor.Motor("pva://BLxxI-MO-TABLE-01:Y")
            # Names and connects devices here
        assert t1x.comm.velocity.source
        assert t1x.name == "t1x"

    """

    def __init__(
        self,
        set_name=True,
        connect=True,
        mock=False,
        timeout: float = 10.0,
    ):
        self._set_name = set_name
        self._connect = connect
        self._mock = mock
        self._timeout = timeout
        self._names_on_enter: set[str] = set()
        self._objects_on_exit: dict[str, Any] = {}

    def _caller_locals(self):
        """Walk up until we find a stack frame that doesn't have us as self"""
        try:
            raise ValueError
        except ValueError:
            _, _, tb = sys.exc_info()
            assert tb, "Can't get traceback, this shouldn't happen"
            caller_frame = tb.tb_frame
            while caller_frame.f_locals.get("self", None) is self:
                caller_frame = caller_frame.f_back
                assert (
                    caller_frame
                ), "No previous frame to the one with self in it, this shouldn't happen"
            return caller_frame.f_locals

    def __enter__(self) -> DeviceCollector:
        # Stash the names that were defined before we were called
        self._names_on_enter = set(self._caller_locals())
        return self

    async def __aenter__(self) -> DeviceCollector:
        return self.__enter__()

    async def _on_exit(self) -> None:
        # Name and kick off connect for devices
        connect_coroutines: dict[str, Coroutine] = {}
        for name, obj in self._objects_on_exit.items():
            if name not in self._names_on_enter and isinstance(obj, Device):
                if self._set_name and not obj.name:
                    obj.set_name(name)
                if self._connect:
                    connect_coroutines[name] = obj.connect(
                        self._mock, timeout=self._timeout
                    )

        # Connect to all the devices
        if connect_coroutines:
            await wait_for_connection(**connect_coroutines)

    async def __aexit__(self, type, value, traceback):
        self._objects_on_exit = self._caller_locals()
        await self._on_exit()

    def __exit__(self, type_, value, traceback):
        self._objects_on_exit = self._caller_locals()
        try:
            fut = call_in_bluesky_event_loop(self._on_exit())
        except RuntimeError as e:
            raise NotConnected(
                "Could not connect devices. Is the bluesky event loop running? See "
                "https://blueskyproject.io/ophyd-async/main/"
                "user/explanations/event-loop-choice.html for more info."
            ) from e
        return fut
