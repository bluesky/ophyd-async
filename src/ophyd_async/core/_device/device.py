"""Base device"""
from __future__ import annotations

from typing import Iterator, Optional, Tuple

from bluesky.protocols import HasName

from ..utils import wait_for_connection


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

    async def connect(self, sim: bool = False):
        """Connect self and all child Devices.

        Parameters
        ----------
        sim:
            If True then connect in simulation mode.
        """
        coros = {
            name: child_device.connect(sim) for name, child_device in self.children()
        }
        if coros:
            await wait_for_connection(**coros)
