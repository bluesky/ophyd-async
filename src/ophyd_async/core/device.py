"""Base device"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import suppress
from typing import Any, Dict, Generator, Iterator, Optional, Set, Tuple, TypeVar

from bluesky.protocols import HasName
from bluesky.run_engine import call_in_bluesky_event_loop

from .utils import NotConnected, wait_for_connection


class Device(HasName):
    """Common base class for all Ophyd Async Devices.

    By default, names and connects all Device children.
    """

    _name: str = ""
    #: The parent Device if it exists
    parent: Optional[Device] = None

    def __init__(self, name: str = "") -> None:
        self.set_name(name)

    @property
    def name(self) -> str:
        """Return the name of the Device"""
        return self._name

    def children(self) -> Iterator[Tuple[str, Device]]:
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
        self._name = name
        for attr_name, child in self.children():
            child_name = f"{name}-{attr_name.rstrip('_')}" if name else ""
            child.set_name(child_name)
            child.parent = self

    async def connect(self, mock: bool = False):
        """Connect self and all child Devices.

        Parameters
        ----------
        mock:
            If True then connect in simulation mode.
        """
        coros = {
            name: child_device.connect(mock) for name, child_device in self.children()
        }
        if coros:
            await wait_for_connection(**coros)


VT = TypeVar("VT", bound=Device)


class DeviceVector(Dict[int, VT], Device):
    def children(self) -> Generator[Tuple[str, Device], None, None]:
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
        self._names_on_enter: Set[str] = set()
        self._objects_on_exit: Dict[str, Any] = {}

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
            return caller_frame.f_locals

    def __enter__(self) -> "DeviceCollector":
        # Stash the names that were defined before we were called
        self._names_on_enter = set(self._caller_locals())
        return self

    async def __aenter__(self) -> "DeviceCollector":
        return self.__enter__()

    async def _on_exit(self) -> None:
        # Name and kick off connect for devices
        tasks: Dict[asyncio.Task, str] = {}
        for name, obj in self._objects_on_exit.items():
            if name not in self._names_on_enter and isinstance(obj, Device):
                if self._set_name and not obj.name:
                    obj.set_name(name)
                if self._connect:
                    task = asyncio.create_task(obj.connect(self._mock))
                    tasks[task] = name
        # Wait for all the signals to have finished
        if tasks:
            await self._wait_for_tasks(tasks)

    async def _wait_for_tasks(self, tasks: Dict[asyncio.Task, str]):
        done, pending = await asyncio.wait(tasks, timeout=self._timeout)
        if pending:
            msg = f"{len(pending)} Devices did not connect:"
            for t in pending:
                t.cancel()
                with suppress(Exception):
                    await t
                e = t.exception()
                msg += f"\n  {tasks[t]}: {type(e).__name__}"
                lines = str(e).splitlines()
                if len(lines) <= 1:
                    msg += f": {e}"
                else:
                    msg += "".join(f"\n    {line}" for line in lines)
            logging.error(msg)
        raised = [t for t in done if t.exception()]
        if raised:
            logging.error(f"{len(raised)} Devices raised an error:")
            for t in raised:
                logging.exception(f"  {tasks[t]}:", exc_info=t.exception())
        if pending or raised:
            raise NotConnected("Not all Devices connected")

    async def __aexit__(self, type, value, traceback):
        self._objects_on_exit = self._caller_locals()
        await self._on_exit()

    def __exit__(self, type_, value, traceback):
        self._objects_on_exit = self._caller_locals()
        return call_in_bluesky_event_loop(self._on_exit())
