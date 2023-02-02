from typing import Dict, Protocol, Type, TypeVar, runtime_checkable

from ophyd.v2.core import Device
from ophyd.v2.epics import EpicsSignalRW

T = TypeVar("T")


class Foo(Protocol):
    bar: int


def check_supports(obj, protocol: Type[T]) -> T:
    assert isinstance(obj, protocol)
    return obj


c = check_supports(object(), Foo)


class PulseBlock(Protocol):
    width: float
    delay: float


c = check_supports(str, PulseBlock)


class PandA(Device):
    _name = ""

    def __init__(self, prefix: str, name: str = "") -> None:
        self._init_prefix = prefix
        self._blocks: Dict[str, Device] = {}
        self.set_name(name)

    @property
    def name(self) -> str:
        return self._name

    def set_name(self, name: str = ""):
        if name and not self._name:
            self._name = name
            for block_name, block in self._blocks.items():
                block.set_name(f"{name}-{block_name}")
                block.parent = self

    async def connect(self, prefix: str = "", sim=False):
        pass

    def pulse_block(self, num: int) -> PulseBlock:
        return check_supports(self._blocks[f"PULSE{num}"], PulseBlock)
