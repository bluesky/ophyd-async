import asyncio
from dataclasses import dataclass, field
from functools import cached_property

import pytest

from ophyd_async.core import (
    FlyableLogic,
    MovableLogic,
    StandardFlyable,
    StandardMovable,
    StandardReadable,
    StandardReadableFormat,
    WatchableAsyncStatus,
    init_devices,
    set_mock_value,
    soft_signal_rw,
)


@dataclass
class RecordingFlyableLogic(FlyableLogic[int, None]):
    """A `FlyableLogic` that records its calls. Not movable, so complete() reports
    no progress to watchers."""

    calls: list[str] = field(default_factory=list)
    prepared_with: list[int] = field(default_factory=list)

    async def on_prepare(self, value: int) -> None:
        self.calls.append("on_prepare")
        self.prepared_with.append(value)

    async def on_kickoff(self, ctx: None) -> None:
        self.calls.append("on_kickoff")

    async def on_complete(self, ctx: None) -> None:
        self.calls.append("on_complete")

    async def stop(self) -> None:
        self.calls.append("stop")


@dataclass
class CtxFlyableLogic(FlyableLogic[int, dict]):
    """A `FlyableLogic` that threads a context dict between its stages."""

    seen: list[tuple[str, dict]] = field(default_factory=list)

    async def on_prepare(self, value: int) -> dict:
        return {"prepared": value}

    async def on_kickoff(self, ctx: dict) -> dict:
        self.seen.append(("kickoff", dict(ctx)))
        ctx["kicked"] = True
        return ctx

    async def on_complete(self, ctx: dict) -> None:
        self.seen.append(("complete", dict(ctx)))


@dataclass
class MovableFlyableLogic(MovableLogic[float], FlyableLogic[float, None]):
    """Both movable and flyable, mirroring how `Motor` combines the two.

    `complete()` should report progress by observing the readback, reusing the
    same watcher-update stream as `StandardMovable.set`.
    """

    async def on_prepare(self, value: float) -> None:
        pass

    async def on_kickoff(self, ctx: None) -> None:
        pass

    async def on_complete(self, ctx: None) -> None:
        # Step the readback towards the target so watchers see progress.
        target = await self.setpoint.get_value()
        for position in (target / 2, target):
            set_mock_value(self.readback, position)
            await asyncio.sleep(0)


class MovableFlyer(StandardMovable[float], StandardFlyable[float, None]):
    def __init__(self, name: str = ""):
        self.readback = soft_signal_rw(float)
        self.setpoint = soft_signal_rw(float)
        super().__init__(name=name)

    @cached_property
    def _logic(self) -> MovableFlyableLogic:
        return MovableFlyableLogic(setpoint=self.setpoint, readback=self.readback)

    @cached_property
    def movable_logic(self) -> MovableFlyableLogic:
        return self._logic

    @cached_property
    def flyable_logic(self) -> MovableFlyableLogic:
        return self._logic


@pytest.fixture
async def recording_flyer():
    """An ephemeral `StandardFlyable` wrapping a fresh `RecordingFlyableLogic`."""
    logic = RecordingFlyableLogic()
    async with init_devices(mock=True):
        flyer = logic.with_device(name="flyer")
    return logic, flyer


async def test_ephemeral_flyable_drives_logic_hooks(recording_flyer):
    logic, flyer = recording_flyer

    assert flyer.name == "flyer"
    assert isinstance(flyer, StandardFlyable)
    # The ephemeral device exposes the same logic instance
    assert flyer.flyable_logic is logic

    await flyer.prepare(5)
    await flyer.kickoff()
    await flyer.complete()

    assert logic.calls == ["on_prepare", "on_kickoff", "on_complete"]
    assert logic.prepared_with == [5]


async def test_flyable_threads_context_between_stages():
    logic = CtxFlyableLogic()
    async with init_devices(mock=True):
        flyer = logic.with_device(name="flyer")

    await flyer.prepare(5)
    await flyer.kickoff()
    await flyer.complete()

    # kickoff sees exactly what prepare produced; complete sees what kickoff added
    assert logic.seen == [
        ("kickoff", {"prepared": 5}),
        ("complete", {"prepared": 5, "kicked": True}),
    ]


async def test_flyable_kickoff_before_prepare_raises(recording_flyer):
    logic, flyer = recording_flyer

    with pytest.raises(RuntimeError, match="prepare.* before kickoff"):
        await flyer.kickoff()
    assert logic.calls == []


async def test_flyable_complete_before_kickoff_raises(recording_flyer):
    logic, flyer = recording_flyer

    with pytest.raises(RuntimeError, match="kickoff.* before complete"):
        await flyer.complete()
    assert logic.calls == []


async def test_flyable_stage_resets_lifecycle(recording_flyer):
    # After prepare+kickoff, staging should reset so a later complete errors again.
    logic, flyer = recording_flyer

    await flyer.prepare(5)
    await flyer.kickoff()
    await flyer.stage()
    with pytest.raises(RuntimeError, match="kickoff.* before complete"):
        await flyer.complete()


async def test_flyable_complete_without_movable_logic_yields_no_updates(
    recording_flyer,
):
    # A flyer whose logic is not a MovableLogic has no readback to report, so
    # complete() is still a WatchableAsyncStatus but calls no watchers.
    logic, flyer = recording_flyer

    await flyer.prepare(5)
    await flyer.kickoff()
    status = flyer.complete()
    assert isinstance(status, WatchableAsyncStatus)
    updates: list[dict] = []
    status.watch(lambda **kwargs: updates.append(kwargs))
    await status

    assert logic.calls == ["on_prepare", "on_kickoff", "on_complete"]
    assert updates == []


async def test_flyable_complete_watches_movable_logic():
    async with init_devices(mock=True):
        flyer = MovableFlyer(name="flyer")

    # Set the fly target on the setpoint without triggering the instant-move mock
    # (so the readback stays at 0 until on_complete steps it).
    set_mock_value(flyer.setpoint, 10.0)
    await flyer.prepare(10.0)
    await flyer.kickoff()
    status = flyer.complete()
    assert isinstance(status, WatchableAsyncStatus)
    updates: list[dict] = []
    status.watch(lambda **kwargs: updates.append(kwargs))
    await status

    # Progress was reported by observing the readback up to the target, with the
    # target read from the setpoint (as StandardMovable.set reports a move).
    assert updates, "expected at least one watcher update"
    assert updates[-1]["current"] == 10.0
    assert {u["initial"] for u in updates} == {0.0}
    assert {u["target"] for u in updates} == {10.0}
    assert {u["name"] for u in updates} == {"flyer"}


async def test_flyable_stage_unstage_default_to_stop(recording_flyer):
    logic, flyer = recording_flyer

    await flyer.stage()
    await flyer.unstage()
    # on_stage/on_unstage both default to stop()
    assert logic.calls == ["stop", "stop"]


async def test_flyable_stage_unstage_can_differ():
    # A flyer (e.g. PmacTrajectoryFlyableLogic) may need distinct stage/unstage.
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

    class ReadableFlyer(StandardReadable, StandardFlyable[int, None]):
        def __init__(self, name: str = ""):
            with self.add_children_as_readables(StandardReadableFormat.HINTED_SIGNAL):
                self.sig = soft_signal_rw(float)
            super().__init__(name=name)

        @cached_property
        def flyable_logic(self) -> FlyableLogic[int, None]:
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
