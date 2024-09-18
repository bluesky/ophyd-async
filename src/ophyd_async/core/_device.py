"""Base device"""

import asyncio
import sys
from collections.abc import Coroutine, Generator, Iterator
from functools import cached_property
from logging import LoggerAdapter, getLogger
from typing import (
    Any,
    Optional,
    TypeVar,
)

from bluesky.protocols import HasName
from bluesky.run_engine import call_in_bluesky_event_loop

from ._utils import DEFAULT_TIMEOUT, NotConnected, wait_for_connection


class Device(HasName):
    """Common base class for all Ophyd Async Devices.

    By default, names and connects all Device children.
    """

    _name: str = ""
    #: The parent Device if it exists
    parent: Optional["Device"] = None
    # None if connect hasn't started, a Task if it has
    _connect_task: asyncio.Task | None = None

    # Used to check if the previous connect was mocked,
    # if the next mock value differs then we fail
    _previous_connect_was_mock = None

    def __init__(self, name: str = "") -> None:
        self.set_name(name)

    @property
    def name(self) -> str:
        """Return the name of the Device"""
        return self._name

    @cached_property
    def log(self):
        return LoggerAdapter(
            getLogger("ophyd_async.devices"), {"ophyd_async_device_name": self.name}
        )

    def children(self) -> Iterator[tuple[str, "Device"]]:
        for attr_name, attr in self.__dict__.items():
            if attr_name != "parent" and isinstance(attr, Device):
                yield attr_name, attr

    def set_name(self, name: str):
        """Set ``self.name=name`` and each ``self.child.name=name+"-child"``.

        Parameters
        ----------
        name:
            New name to set
        """

        # Ensure self.log is recreated after a name change
        if hasattr(self, "log"):
            del self.log

        self._name = name
        for attr_name, child in self.children():
            child_name = f"{name}-{attr_name.rstrip('_')}" if name else ""
            child.set_name(child_name)
            child.parent = self

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

        if (
            self._previous_connect_was_mock is not None
            and self._previous_connect_was_mock != mock
        ):
            raise RuntimeError(
                f"`connect(mock={mock})` called on a `Device` where the previous "
                f"connect was `mock={self._previous_connect_was_mock}`. Changing mock "
                "value between connects is not permitted."
            )
        self._previous_connect_was_mock = mock

        # If previous connect with same args has started and not errored, can use it
        can_use_previous_connect = self._connect_task and not (
            self._connect_task.done() and self._connect_task.exception()
        )
        if force_reconnect or not can_use_previous_connect:
            # Kick off a connection
            coros = {
                name: child_device.connect(
                    mock, timeout=timeout, force_reconnect=force_reconnect
                )
                for name, child_device in self.children()
            }
            self._connect_task = asyncio.create_task(wait_for_connection(**coros))

        assert self._connect_task, "Connect task not created, this shouldn't happen"
        # Wait for it to complete
        await self._connect_task


VT = TypeVar("VT", bound=Device)


class DeviceVector(dict[int, VT], Device):
    """
    Defines device components with indices.

    In the below example, foos becomes a dictionary on the parent device
    at runtime, so parent.foos[2] returns a FooDevice. For example usage see
    :class:`~ophyd_async.epics.demo.DynamicSensorGroup`
    """

    def children(self) -> Generator[tuple[str, Device], None, None]:
        for attr_name, attr in self.items():
            if isinstance(attr, Device):
                yield str(attr_name), attr


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

    def __enter__(self) -> "DeviceCollector":
        # Stash the names that were defined before we were called
        self._names_on_enter = set(self._caller_locals())
        return self

    async def __aenter__(self) -> "DeviceCollector":
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
