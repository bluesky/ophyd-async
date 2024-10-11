from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine, Iterator, Mapping, MutableMapping
from logging import LoggerAdapter, getLogger
from typing import Any, TypeVar

from bluesky.protocols import HasName
from bluesky.run_engine import call_in_bluesky_event_loop

from ._protocol import Connectable
from ._utils import DEFAULT_TIMEOUT, NotConnected, wait_for_connection


class DeviceConnectCache:
    mock_arg: bool | None = None
    task: asyncio.Task | None = None

    async def need_connect(self, mock: bool, force_reconnect: bool) -> bool:
        can_use_previous_connect = (
            mock is self.mock_arg
            and self.task
            and not (self.task.done() and self.task.exception())
        )
        if can_use_previous_connect and not force_reconnect:
            assert self.task, "Connect caching not working"
            await self.task
            return False
        else:
            return True

    async def do_connect(self, mock: bool, coro: Coroutine) -> None:
        self.mock_arg = mock
        self.task = asyncio.create_task(coro)
        await self.task


class DeviceBase(HasName, Connectable):
    """Common base class for all Ophyd Async Devices."""

    _name: str = ""
    #: The parent Device if it exists
    parent: DeviceBase | None = None

    def __init__(
        self,
        name: str = "",
    ) -> None:
        self._connect_cache = DeviceConnectCache()
        self.set_name(name)

    @property
    def name(self) -> str:
        """Return the name of the Device"""
        return self._name

    def set_name(self, name: str):
        self._name = name
        # Ensure self.log is recreated after a name change
        self.log = LoggerAdapter(
            getLogger("ophyd_async.devices"), {"ophyd_async_device_name": self.name}
        )


DeviceBaseT = TypeVar("DeviceBaseT", bound=DeviceBase)


class DeviceBackend:
    def __init__(self, device_type: type[Device]):
        self.device_type = device_type
        self.children: dict[str, DeviceBase] = {}

    # TODO: we will add some mechanism of invalidating the cache here later
    async def connect(self, mock: bool, timeout: float, force_reconnect: bool) -> None:
        coros = {
            name: child_device.connect(
                mock=mock, timeout=timeout, force_reconnect=force_reconnect
            )
            for name, child_device in self.children.items()
        }
        await wait_for_connection(**coros)


class Device(DeviceBase):
    """Common base class for all Ophyd Async Devices."""

    _backend: DeviceBackend

    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        # Need to make the backend first in case any children are
        # created before the super().__init__ call
        instance._backend = DeviceBackend(cls)  # noqa: SLF001
        return instance

    def __init__(self, name: str = "", backend: DeviceBackend | None = None) -> None:
        if backend:
            # Copy into the new backend the children that have already been added
            backend.children.update(self._backend.children)
            self._backend = backend
        super().__init__(name)

    def _set_child_name(self, child: DeviceBase, child_name: str):
        child_name = f"{self.name}-{child_name.rstrip('_')}" if self.name else ""
        child.set_name(child_name)
        child.parent = self

    def set_name(self, name: str):
        super().set_name(name)
        for child_name, child in self._backend.children.items():
            self._set_child_name(child, child_name)

    def children(self) -> Iterator[tuple[str, DeviceBase]]:
        yield from self._backend.children.items()

    def __setattr__(self, name: str, child: DeviceBase) -> None:
        if name != "parent" and isinstance(child, DeviceBase):
            self._backend.children[name] = child
            self._set_child_name(child, name)
        else:
            super().__setattr__(name, child)

    def __getattr__(self, name: str) -> DeviceBase:
        child = self._backend.children.get(name, None)
        if child is None:
            txt = f"'{type(self).__name__}' object has no attribute '{name}'"
            if name == "_connect_cache":
                txt += ". Is super().__init__? being called at the end of __init__?"
            raise AttributeError(txt)
        else:
            return child

    async def connect(
        self,
        mock: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        force_reconnect: bool = False,
    ):
        if await self._connect_cache.need_connect(mock, force_reconnect):
            coro = self._backend.connect(mock, timeout, force_reconnect)
            await self._connect_cache.do_connect(mock, coro)
            # Backend might make more children, so make sure they are named
            self.set_name(self.name)


class DeviceVector(MutableMapping[int, DeviceBaseT], DeviceBase):
    """
    Defines device components with indices.

    In the below example, foos becomes a dictionary on the parent device
    at runtime, so parent.foos[2] returns a FooDevice. For example usage see
    :class:`~ophyd_async.epics.demo.DynamicSensorGroup`
    """

    def __init__(
        self,
        children: Mapping[int, DeviceBaseT],
        name: str = "",
    ) -> None:
        self._children = dict(children)
        super().__init__(name=name)

    def _set_child_name(self, child: DeviceBase, index: int):
        child.set_name(f"{self.name}-{index}" if self.name else "")

    def set_name(self, name: str):
        super().set_name(name)
        for index, child in self._children.items():
            self._set_child_name(child, index)

    def __setattr__(self, name: str, child: Device) -> None:
        if name != "parent" and isinstance(child, DeviceBase):
            raise AttributeError(
                "DeviceVector can only have integer named children, "
                "set via device_vector[i] = child"
            )
        else:
            super().__setattr__(name, child)

    def __getitem__(self, key: int) -> DeviceBaseT:
        assert isinstance(key, int), f"Expected int, got {key}"
        return self._children[key]

    def __setitem__(self, key: int, value: DeviceBaseT) -> None:
        assert isinstance(key, int), f"Expected int, got {key}"
        assert isinstance(value, DeviceBase), f"Expected Device, got {value}"
        self._children[key] = value
        value.parent = self
        self._set_child_name(value, key)

    def __delitem__(self, key: int) -> None:
        assert isinstance(key, int), f"Expected int, got {key}"
        del self._children[key]

    def __iter__(self) -> Iterator[int]:
        yield from self._children

    def __len__(self) -> int:
        return len(self._children)

    async def connect(
        self,
        mock: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
        force_reconnect: bool = False,
    ):
        if await self._connect_cache.need_connect(mock, force_reconnect):
            coros = {
                str(name): child_device.connect(
                    mock=mock, timeout=timeout, force_reconnect=force_reconnect
                )
                for name, child_device in self._children.items()
            }
            await self._connect_cache.do_connect(mock, wait_for_connection(**coros))


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
            if name not in self._names_on_enter and isinstance(obj, DeviceBase):
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
