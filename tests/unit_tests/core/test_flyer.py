from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import cached_property

import pytest

from ophyd_async.core import (
    FlyableLogic,
    StandardFlyable,
    WatchableAsyncStatus,
    WatcherUpdate,
    init_devices,
)


@dataclass
class RecordingFlyableLogic(FlyableLogic[int]):
    """A `FlyableLogic` that records its calls and reports progress on complete."""

    calls: list[str] = field(default_factory=list)
    prepared_with: list[int] = field(default_factory=list)

    async def on_prepare(self, value: int) -> None:
        self.calls.append("on_prepare")
        self.prepared_with.append(value)

    async def on_kickoff(self) -> None:
        self.calls.append("on_kickoff")

    async def on_complete(self) -> AsyncIterator[WatcherUpdate]:
        self.calls.append("on_complete")
        for i in (1, 2):
            yield WatcherUpdate(current=i, initial=0, target=2)

    async def stop(self) -> None:
        self.calls.append("stop")


async def test_ephemeral_flyable_drives_logic_hooks():
    logic = RecordingFlyableLogic()
    async with init_devices(mock=True):
        flyer = logic.with_device(name="flyer")

    assert flyer.name == "flyer"
    assert isinstance(flyer, StandardFlyable)
    # The ephemeral device exposes the same logic instance
    assert flyer.flyable_logic is logic

    await flyer.prepare(5)
    await flyer.kickoff()
    await flyer.complete()

    assert logic.calls == ["on_prepare", "on_kickoff", "on_complete"]
    assert logic.prepared_with == [5]


async def test_flyable_complete_is_watchable():
    logic = RecordingFlyableLogic()
    async with init_devices(mock=True):
        flyer = logic.with_device(name="flyer")

    status = flyer.complete()
    assert isinstance(status, WatchableAsyncStatus)
    currents: list[int] = []
    status.watch(lambda current, **_: currents.append(current))
    await status

    assert currents == [1, 2]


@pytest.mark.parametrize("success", [True, False])
async def test_flyable_stage_unstage_call_stop(success: bool):
    logic = RecordingFlyableLogic()
    async with init_devices(mock=True):
        flyer = logic.with_device(name="flyer")

    await flyer.stage()
    await flyer.unstage()
    # stage() delegates to unstage(), so stop() is called for each
    assert logic.calls == ["stop", "stop"]


async def test_flyable_as_mixin_subclass():
    logic = RecordingFlyableLogic()

    class MyFlyer(StandardFlyable[int]):
        @cached_property
        def flyable_logic(self) -> FlyableLogic[int]:
            return logic

    async with init_devices(mock=True):
        flyer = MyFlyer(name="my_flyer")

    await flyer.prepare(3)
    assert logic.prepared_with == [3]
