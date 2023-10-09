from abc import ABC, abstractmethod
from typing import Sequence
from .._device.device import Device


class Driver(ABC, Device):
    """Subclass of Device providing a shape to acquired data collections."""

    @abstractmethod
    async def shape(self) -> Sequence[int]:
        """The shape of an aquisition."""
