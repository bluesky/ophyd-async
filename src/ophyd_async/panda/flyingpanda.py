from typing import Dict, Iterable, Iterator

from bluesky.protocols import Descriptor, Flyable, PartialEvent
from ophyd_async.core import AsyncStatus, wait_for_value
from ophyd_async.panda import PandA, tables


class FlyingPanda(Flyable):
    def __init__(self, panda):
        self.dev: PandA = panda

    @property
    def name(self) -> str:
        return self.dev.name

    async def set_frames(self, frames: Iterable[tables.Frame]) -> None:
        table = tables.build_table(*zip(*frames))
        await self.dev.seq[1].tables.set(table)

    @AsyncStatus.wrap
    async def kickoff(self) -> None:
        # NOTE: the first of these DOES NOT WORK. This is a bug and is being tracked:
        # https://github.com/bluesky/ophyd-async/issues/13
        # you will need to actually do caput/pvput to make prescale_units ms.
        await self.dev.seq[1].prescale_units.set("ms")
        await self.dev.seq[1].prescale.set(1)
        await self.dev.seq[1].enable.set("ZERO")
        await self.dev.seq[1].repeats.set(1)
        await self.dev.seq[1].enable.set("ONE")
        await wait_for_value(self.dev.seq[1].active, "1", 5)

    @AsyncStatus.wrap
    async def complete(self) -> None:
        await wait_for_value(self.dev.seq[1].active, "0", 20)
        await self.dev.seq[1].enable.set("ZERO")

    def collect(self) -> Iterator[PartialEvent]:
        yield from iter([])

    def describe_collect(self) -> Dict[str, Dict[str, Descriptor]]:
        return {}
