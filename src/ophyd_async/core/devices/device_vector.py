from typing import Dict, TypeVar

from ..utils import wait_for_connection
from .device import Device

VT = TypeVar("VT", bound=Device)


class DeviceVector(Dict[int, VT], Device):
    def set_name(self, parent_name: str):
        self._name = parent_name
        for name, device in self.items():
            device.set_name(f"{parent_name}-{name}")
            device.parent = self

    async def connect(self, sim: bool = False):
        coros = {str(k): d.connect(sim) for k, d in self.items()}
        await wait_for_connection(**coros)
