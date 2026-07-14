from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import cached_property

import pytest

from ophyd_async.core import (
    FlyableLogic,
    StandardFlyable,
    StandardReadable,
    StandardReadableFormat,
    WatchableAsyncStatus,
    WatcherUpdate,
    init_devices,
    soft_signal_rw,
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


async def test_flyable_stage_unstage_default_to_stop():
    logic = RecordingFlyableLogic()
    async with init_devices(mock=True):
        flyer = logic.with_device(name="flyer")

    await flyer.stage()
    await flyer.unstage()
    # on_stage/on_unstage both default to stop()
    assert logic.calls == ["stop", "stop"]


async def test_flyable_stage_unstage_can_differ():
    # A flyer (e.g. PmacTrajectoryTriggerLogic) may need distinct stage/unstage.
    @dataclass
    class StageUnstageLogic(RecordingFlyableLogic):
        async def on_stage(self) -> None:
            self.calls.append("on_stage")

        async def on_unstage(self) -> None:
            self.calls.append("on_unstage")

    logic = StageUnstageLogic()
    async with init_devices(mock=True):
        flyer = logic.with_device(name="flyer")

    await flyer.stage()
    await flyer.unstage()
    assert logic.calls == ["on_stage", "on_unstage"]


async def test_flyable_composes_with_readable_staging():
    # Motor is StandardMovable + StandardFlyable + StandardReadable; the flyer's
    # stage/unstage must NOT shadow StandardReadable's caching of hinted signals.
    logic = RecordingFlyableLogic()

    class ReadableFlyer(StandardReadable, StandardFlyable[int]):
        def __init__(self, name: str = ""):
            with self.add_children_as_readables(StandardReadableFormat.HINTED_SIGNAL):
                self.sig = soft_signal_rw(float)
            super().__init__(name=name)

        @cached_property
        def flyable_logic(self) -> FlyableLogic[int]:
            return logic

    async with init_devices(mock=True):
        device = ReadableFlyer(name="rf")

    await device.stage()
    # StandardReadable contribution: the hinted signal is now cached (this raises
    # "not being monitored" if StandardFlyable.stage had shadowed it).
    await device.sig.read(cached=True)
    # StandardFlyable contribution ran too.
    assert logic.calls == ["stop"]

    await device.unstage()
    assert logic.calls == ["stop", "stop"]
    # The cache is torn down on unstage.
    with pytest.raises(RuntimeError, match="not being monitored"):
        await device.sig.read(cached=True)
