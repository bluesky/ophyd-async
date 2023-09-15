"""Dictionary which can contain mappings between integers and devices."""

from typing import Dict, Generator, Tuple, TypeVar

from .device import Device

VT = TypeVar("VT", bound=Device)


class DeviceVector(Dict[int, VT], Device):
    def children(self) -> Generator[Tuple[str, Device], None, None]:
        for attr_name, attr in self.items():
            if isinstance(attr, Device):
                yield str(attr_name), attr
