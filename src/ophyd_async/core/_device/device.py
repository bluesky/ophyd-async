"""Base device"""

from typing import Generator, Optional, Tuple

from bluesky.protocols import HasName

from ..utils import wait_for_connection


class Device(HasName):
    """Common base class for all Ophyd Async Devices.

    By default, names and connects all Device children.
    """

    _name: str = ""
    #: The parent Device if it exists
    parent: Optional["Device"] = None

    def __init__(self, name: str = "") -> None:
        self.set_name(name)

    @property
    def name(self) -> str:
        """Return the name of the Device"""
        return self._name

    def set_name(self, name: str):
        """Set ``self.name=name`` and each ``self.child.name=name+"-child"``.

        Parameters
        ----------
        name:
            New name to set
        """
        self._name = name
        name_children(self, name)

    async def connect(self, sim: bool = False):
        """Connect self and all child Devices.

        Parameters
        ----------
        sim:
            If True then connect in simulation mode.
        """
        await connect_children(self, sim)


async def connect_children(device: Device, sim: bool):
    """Call ``child.connect(sim)`` on all child devices in parallel.

    Typically used to implement `Device.connect` like this::

        async def connect(self, sim=False):
            await connect_children(self, sim)
    """

    coros = {
        name: child_device.connect(sim)
        for name, child_device in get_device_children(device)
    }
    if coros:
        await wait_for_connection(**coros)


def name_children(device: Device, name: str):
    """Call ``child.set_name(child_name)`` on all child devices in series."""
    for attr_name, child in get_device_children(device):
        child_name = f"{name}-{attr_name.rstrip('_')}" if name else ""
        child.set_name(child_name)
        child.parent = device


def get_device_children(device: Device) -> Generator[Tuple[str, Device], None, None]:
    for attr_name, attr in device.__dict__.items():
        if attr_name != "parent" and isinstance(attr, Device):
            yield attr_name, attr
