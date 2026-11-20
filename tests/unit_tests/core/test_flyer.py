import asyncio
import sys
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, cast
from unittest.mock import Mock

import pytest

from ophyd_async.core import (
    KICKED_OFF,
    AsyncStatus,
    Device,
    FlyableLogic,
    MovableLogic,
    StandardFlyable,
    StandardMovable,
    StandardReadable,
    StandardReadableFormat,
    TransitionError,
    WatchableAsyncStatus,
    WatcherUpdate,
    init_devices,
    set_mock_value,
    soft_signal_rw,
    watch_readback,
)
from ophyd_async.testing import wait_for_pending_wakeups


@dataclass
class RecordingFlyableLogic(FlyableLogic[int]):
    """A `FlyableLogic` that records its calls. Not movable, so prepare() and
    complete() report no progress to watchers."""

    calls: list[str] = field(default_factory=list)
    prepared_with: list[int] = field(default_factory=list)

    async def prepare_to_fly(
        self, name: str, value: int, previous_ctx: None
    ) -> AsyncGenerator[None, None]:
        self.calls.append("prepare_to_fly")
        self.prepared_with.append(value)
        yield None

    async def fly(self, ctx: None) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        self.calls.append("kicking off")
        yield KICKED_OFF
        self.calls.append("completing")

    async def ensure_stopped(self) -> None:
        self.calls.append("ensure_stopped")


@dataclass(frozen=True)
class Ctx:
    value: int
    # Anything that changes during the scan is an object the ctx holds
    log: list[str] = field(default_factory=list)


@dataclass
class CtxFlyableLogic(FlyableLogic[int, Ctx]):
    """A `FlyableLogic` that passes a ctx from prepare_to_fly to fly."""

    seen: list[Ctx] = field(default_factory=list)
    made: list[Ctx] = field(default_factory=list)

    async def prepare_to_fly(
        self, name: str, value: int, previous_ctx: None
    ) -> AsyncGenerator[Ctx, None]:
        self.made.append(Ctx(value))
        yield self.made[0]

    async def fly(self, ctx: Ctx) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        self.seen.append(ctx)
        yield KICKED_OFF

    async def ensure_stopped(self) -> None: ...


@dataclass
class MovableFlyableLogic(MovableLogic[float], FlyableLogic[float, float]):
    """Both movable and flyable, mirroring how `Motor` combines the two.

    `prepare()` and `complete()` should report progress by watching the readback
    with `watch_readback`, reusing the same watcher updates as
    `StandardMovable.set`.
    """

    async def _step_to(self, target: float) -> None:
        # Step the readback towards the target so watchers see progress.
        for position in (target / 2, target):
            set_mock_value(self.readback, position)
            await asyncio.sleep(0)

    async def prepare_to_fly(
        self, name: str, value: float, previous_ctx: None
    ) -> AsyncGenerator[float | WatcherUpdate, None]:
        yield value
        async with AsyncStatus(self._step_to(value)) as status:
            async for update in watch_readback(self, status, target=value):
                yield update

    async def fly(self, ctx: float) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        async with AsyncStatus(self._step_to(2 * ctx)) as status:
            yield KICKED_OFF
            async for update in watch_readback(self, status, 2 * ctx, initial=ctx):
                yield update

    async def ensure_stopped(self) -> None: ...


class MovableFlyer(StandardMovable[float], StandardFlyable[float, float]):
    def __init__(self, name: str = ""):
        self.readback = soft_signal_rw(float)
        self.setpoint = soft_signal_rw(float)
        super().__init__(name=name)

    @cached_property
    def logic(self) -> MovableFlyableLogic:
        return MovableFlyableLogic(setpoint=self.setpoint, readback=self.readback)


@dataclass
class BlockingFlyableLogic(RecordingFlyableLogic):
    """Blocks forever in the named verb's part of a hook, so it is left in flight."""

    block: str = ""

    async def _maybe_block(self, verb: str) -> None:
        self.calls.append(verb)
        if self.block == verb:
            await asyncio.Event().wait()

    async def prepare_to_fly(
        self, name: str, value: int, previous_ctx: None
    ) -> AsyncGenerator[None, None]:
        await self._maybe_block("prepare")
        yield None

    async def fly(self, ctx: None) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        await self._maybe_block("kickoff")
        yield KICKED_OFF
        await self._maybe_block("complete")


@dataclass
class FlyingLogic(FlyableLogic[int]):
    """Kicks off a status that runs until cancelled; `fail` raises after kickoff
    instead of waiting for it."""

    fail: bool = False
    fly_statuses: list[AsyncStatus] = field(default_factory=list)
    running_when_stopped: list[bool] = field(default_factory=list)

    async def prepare_to_fly(
        self, name: str, value: int, previous_ctx: None
    ) -> AsyncGenerator[None, None]:
        yield None

    async def fly(self, ctx: None) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        async with AsyncStatus(asyncio.Event().wait()) as status:
            self.fly_statuses.append(status)
            yield KICKED_OFF
            await asyncio.sleep(0)
            if self.fail:
                raise ValueError("bad fly")
            await status

    async def ensure_stopped(self) -> None:
        self.running_when_stopped.append(
            any(not status.done for status in self.fly_statuses)
        )


async def make_staged_flyer(logic: FlyableLogic[Any, Any]):
    async with init_devices(mock=True):
        flyer = logic.with_device(name="flyer")
    await flyer.stage()
    return flyer


@pytest.fixture
async def recording_flyer():
    """A staged ephemeral `StandardFlyable` wrapping a `RecordingFlyableLogic`."""
    logic = RecordingFlyableLogic()
    flyer = await make_staged_flyer(logic)
    logic.calls.clear()  # forget the ensure_stopped() from stage
    return logic, flyer


async def test_ephemeral_flyable_drives_logic_hooks(recording_flyer):
    logic, flyer = recording_flyer

    assert flyer.name == "flyer"
    assert isinstance(flyer, StandardFlyable)
    # The ephemeral device exposes the same logic instance
    assert flyer.logic is logic

    # Every point of a scan reuses the staged flyer: FLOWN can prepare again
    for value in (5, 6):
        await flyer.prepare(value)
        await flyer.kickoff()
        await flyer.complete()

    assert logic.calls == ["prepare_to_fly", "kicking off", "completing"] * 2
    assert logic.prepared_with == [5, 6]
    await flyer.unstage()
    assert logic.calls[-1] == "ensure_stopped"


async def test_flyable_passes_ctx_to_fly():
    logic = CtxFlyableLogic()
    flyer = await make_staged_flyer(logic)

    await flyer.prepare(5)
    await flyer.kickoff()
    await flyer.complete()

    # fly sees the one ctx prepare_to_fly yielded
    assert logic.seen == [logic.made[0]]
    assert logic.seen[0] is logic.made[0]


@pytest.mark.parametrize(
    "setup, verb, current",
    [
        # Not staged
        ([], "prepare", "UNSTAGED"),
        # Out of order
        (["stage"], "kickoff", "STAGED"),
        (["stage"], "complete", "STAGED"),
        (["stage", "prepare"], "complete", "PREPARED"),
        # Prepared: kickoff before preparing again
        (["stage", "prepare"], "prepare", "PREPARED"),
        (["stage", "prepare", "kickoff"], "kickoff", "FLYING"),
        # A running fly cannot be prepared over
        (["stage", "prepare", "kickoff"], "prepare", "FLYING"),
        # Flown: only a new prepare (or complete, stage, unstage) is allowed
        (["stage", "prepare", "kickoff", "complete"], "kickoff", "FLOWN"),
        # A new prepare forgets the last fly
        (
            ["stage", "prepare", "kickoff", "complete", "prepare"],
            "complete",
            "PREPARED",
        ),
    ],
)
async def test_flyable_verb_in_the_wrong_state_raises(setup, verb, current):
    # A fly that is kicked off keeps flying until completed
    logic = BlockingFlyableLogic(block="complete" if setup[-1:] == ["kickoff"] else "")
    async with init_devices(mock=True):
        flyer = logic.with_device(name="flyer")
    for step in setup:
        await (getattr(flyer, step)(1) if step == "prepare" else getattr(flyer, step)())
    logic.calls.clear()

    with pytest.raises(TransitionError, match=rf"flyer.*from {current}.*allowed"):
        await (getattr(flyer, verb)(1) if verb == "prepare" else getattr(flyer, verb)())
    assert logic.calls == []
    await flyer.unstage()


@pytest.mark.parametrize("verb", ["prepare", "kickoff", "complete"])
async def test_stage_during_a_verb_raises_and_unstage_cancels_it(verb):
    logic = BlockingFlyableLogic(block=verb)
    flyer = await make_staged_flyer(logic)
    verbs = {
        "prepare": lambda: flyer.prepare(1),
        "kickoff": flyer.kickoff,
        "complete": flyer.complete,
    }
    running = None
    for name, start in verbs.items():
        running = start()
        if name == verb:
            break
        await running
    await wait_for_pending_wakeups()
    assert logic.calls[-1] == verb

    # Only unstage can end a verb that is in flight
    with pytest.raises(TransitionError, match="cannot go to STAGING"):
        await flyer.stage()
    await flyer.unstage()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(cast(AsyncStatus, running), timeout=1)

    # The cancelled verb did not touch the state unstage left behind
    logic.block = ""
    await flyer.stage()
    await flyer.prepare(2)


async def test_flyable_unstage_resets_lifecycle(recording_flyer):
    # After prepare+kickoff, unstaging should reset so a later complete errors.
    logic, flyer = recording_flyer

    await flyer.prepare(5)
    await flyer.kickoff()
    await flyer.unstage()
    await flyer.stage()
    with pytest.raises(TransitionError, match="from STAGED"):
        await flyer.complete()


async def test_flyable_stage_twice_raises(recording_flyer):
    logic, flyer = recording_flyer

    with pytest.raises(TransitionError, match="cannot go to STAGING from STAGED"):
        await flyer.stage()
    # Nothing ran, and it is still staged
    assert logic.calls == []
    await flyer.prepare(1)


async def test_flyable_without_progress_yields_no_updates(recording_flyer):
    # A logic whose hooks yield no updates reports no progress, but prepare()
    # and complete() are still watchable
    logic, flyer = recording_flyer

    prepare_watcher, complete_watcher = Mock(), Mock()
    status = flyer.prepare(5)
    assert isinstance(status, WatchableAsyncStatus)
    status.watch(prepare_watcher)
    await status
    await flyer.kickoff()
    status = flyer.complete()
    assert isinstance(status, WatchableAsyncStatus)
    status.watch(complete_watcher)
    await status

    prepare_watcher.assert_not_called()
    complete_watcher.assert_not_called()
    assert logic.calls == ["prepare_to_fly", "kicking off", "completing"]


async def test_flyable_reports_progress_from_logic():
    async with init_devices(mock=True):
        flyer = MovableFlyer(name="flyer")
    await flyer.stage()

    prepare_watcher, complete_watcher = Mock(), Mock()
    status = flyer.prepare(10.0)
    assert isinstance(status, WatchableAsyncStatus)
    status.watch(prepare_watcher)
    await status
    await flyer.kickoff()
    status = flyer.complete()
    assert isinstance(status, WatchableAsyncStatus)
    status.watch(complete_watcher)
    await status

    # Progress is stamped with the flyer's name, and prepare() moves to its
    # start before kickoff is allowed
    updates = [c.kwargs for c in prepare_watcher.call_args_list]
    assert [u["current"] for u in updates] == [0.0, 5.0, 10.0]
    assert {u["initial"] for u in updates} == {0.0}
    assert {u["target"] for u in updates} == {10.0}
    assert {u["name"] for u in updates} == {"flyer"}
    updates = [c.kwargs for c in complete_watcher.call_args_list]
    assert updates[-1]["current"] == 20.0
    assert {u["initial"] for u in updates} == {10.0}
    assert {u["target"] for u in updates} == {20.0}
    assert {u["name"] for u in updates} == {"flyer"}


async def test_watch_readback_reraises_the_status_error():
    async with init_devices(mock=True):
        flyer = MovableFlyer(name="flyer")

    async def fail():
        await asyncio.sleep(0)
        raise ValueError("boom")

    updates = []
    with pytest.raises(ValueError, match="boom"):
        async with AsyncStatus(fail()) as status:
            async for update in watch_readback(flyer.logic, status, target=1.0):
                updates.append(update)
    # Initial defaults to the readback now
    assert {u.initial for u in updates} == {0.0}


@pytest.mark.parametrize("prepare", [False, True])
async def test_unstage_always_stops(recording_flyer, prepare):
    logic, flyer = recording_flyer
    if prepare:
        await flyer.prepare(1)

    await flyer.unstage()
    assert "ensure_stopped" in logic.calls

    # ensure_ready defaults to ensure_stopped
    logic.calls.clear()
    await flyer.stage()
    assert logic.calls == ["ensure_stopped"]
    await flyer.unstage()
    assert logic.calls == ["ensure_stopped", "ensure_stopped"]


@dataclass
class FailingFlyableLogic(RecordingFlyableLogic):
    """Raises from the hook named by `failing`."""

    failing: str = ""

    def _maybe_fail(self, hook: str) -> None:
        if self.failing == hook:
            raise ValueError(f"bad {hook}")

    async def prepare_to_fly(
        self, name: str, value: int, previous_ctx: None
    ) -> AsyncGenerator[None, None]:
        self._maybe_fail("prepare_to_fly")
        yield None

    async def fly(self, ctx: None) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        self._maybe_fail("kickoff")
        yield KICKED_OFF
        self._maybe_fail("complete")

    async def ensure_ready(self) -> None:
        self._maybe_fail("ensure_ready")

    async def ensure_stopped(self) -> None:
        self._maybe_fail("ensure_stopped")


@pytest.mark.parametrize(
    "failing, verbs",
    [
        ("ensure_ready", ["stage"]),
        ("prepare_to_fly", ["stage", "prepare"]),
        ("kickoff", ["stage", "prepare", "kickoff"]),
        ("complete", ["stage", "prepare", "kickoff", "complete"]),
        ("ensure_stopped", ["stage", "prepare", "unstage"]),
    ],
)
async def test_an_error_from_a_hook_is_raised(failing, verbs):
    logic = FailingFlyableLogic(failing=failing)
    async with init_devices(mock=True):
        flyer = logic.with_device(name="flyer")

    def call(verb: str):
        return flyer.prepare(1) if verb == "prepare" else getattr(flyer, verb)()

    *before, last = verbs
    for verb in before:
        await call(verb)
    with pytest.raises(ValueError, match=f"bad {failing}"):
        await call(last)


async def test_flyable_stage_unstage_can_differ():
    # A flyer (e.g. PmacTrajectoryFlyableLogic) may need distinct stage/unstage.
    @dataclass
    class StageUnstageLogic(RecordingFlyableLogic):
        async def ensure_ready(self) -> None:
            self.calls.append("ensure_ready")

    logic = StageUnstageLogic()
    async with init_devices(mock=True):
        flyer = logic.with_device(name="flyer")

    await flyer.stage()
    assert logic.calls == ["ensure_ready"]
    await flyer.prepare(1)
    # prepare() does not get it ready again
    assert logic.calls == ["ensure_ready", "prepare_to_fly"]
    await flyer.unstage()
    assert logic.calls == ["ensure_ready", "prepare_to_fly", "ensure_stopped"]


@pytest.mark.parametrize(
    "stale, replacement",
    [
        ("on_prepare", "prepare_to_fly"),
        ("on_kickoff", "fly"),
        ("on_complete", "fly"),
        ("on_stage", "ensure_ready"),
        ("on_unstage", "ensure_stopped"),
        ("stop", "ensure_stopped"),
    ],
)
def test_flyable_logic_defining_a_stale_hook_raises(stale: str, replacement: str):
    with pytest.raises(
        TypeError,
        match=rf"StaleLogic defines {stale}, which .*{stale} -> {replacement}",
    ):
        type("StaleLogic", (RecordingFlyableLogic,), {stale: lambda self: None})


@pytest.mark.parametrize(
    "logic_class, kwargs, missing",
    [
        (MovableLogic, {"setpoint": None, "readback": None}, "ensure_stopped"),
        (FlyableLogic, {}, "ensure_stopped, fly, prepare_to_fly"),
    ],
)
def test_logic_missing_an_abstract_hook_raises_at_construction(
    logic_class: type, kwargs: dict, missing: str
):
    incomplete = type("Incomplete", (logic_class,), {})
    with pytest.raises(TypeError, match=r"Incomplete.*abstract") as exc_info:
        incomplete(**kwargs)
    # The order of the missing methods in the message varies between Pythons
    for name in missing.split(", "):
        assert name in str(exc_info.value)


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
        def logic(self) -> FlyableLogic[int, None]:
            return logic

    async with init_devices(mock=True):
        device = ReadableFlyer(name="rf")

    await device.stage()
    # StandardReadable contribution: the hinted signal is now cached (this raises
    # "not being monitored" if StandardFlyable.stage had shadowed it).
    await device.sig.read(cached=True)
    # StandardFlyable contribution ran too.
    assert logic.calls == ["ensure_stopped"]

    await device.unstage()
    # Unstage stops even though it was not prepared
    assert logic.calls == ["ensure_stopped", "ensure_stopped"]
    # The cache is torn down on unstage.
    with pytest.raises(RuntimeError, match="not being monitored"):
        await device.sig.read(cached=True)


# Bug: fly statuses were never cancelled
async def test_unstage_cancels_the_running_fly_before_stopping_the_hardware():
    logic = FlyingLogic()
    flyer = await make_staged_flyer(logic)
    await flyer.prepare(1)
    await flyer.kickoff()
    await asyncio.sleep(0)
    assert not logic.fly_statuses[0].done

    await flyer.unstage()

    assert logic.fly_statuses[0].task.cancelled()
    # Neither stage's nor unstage's ensure_stopped saw the fly running
    assert logic.running_when_stopped == [False, False]


# Bug: an unstage() cancelled before it awaited the fly left it running unowned
async def test_cancelled_unstage_still_cancels_the_fly():
    logic = FlyingLogic()
    flyer = await make_staged_flyer(logic)
    await flyer.prepare(1)
    await flyer.kickoff()

    unstaging = flyer.unstage()
    await asyncio.sleep(0)
    unstaging.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await unstaging
    await wait_for_pending_wakeups()

    assert logic.fly_statuses[0].task.cancelled()


# Bug: an unstage() that failed or was cancelled while stopping left its ctx
# behind as the next prepare's previous_ctx
@pytest.mark.parametrize("stop", ["fail", "hang"])
async def test_restage_after_an_interrupted_unstage_starts_afresh(stop: str):
    @dataclass
    class StopLogic(FlyableLogic[int, int]):
        stopping: str = ""
        previous_ctxs: list[int | None] = field(default_factory=list)

        async def prepare_to_fly(
            self, name: str, value: int, previous_ctx: int | None
        ) -> AsyncGenerator[int, None]:
            self.previous_ctxs.append(previous_ctx)
            yield value

        async def fly(self, ctx: int) -> AsyncGenerator[KICKED_OFF, None]:
            yield KICKED_OFF

        async def ensure_stopped(self) -> None:
            if self.stopping == "fail":
                raise ValueError("stop failed")
            elif self.stopping == "hang":
                await asyncio.Event().wait()

    logic = StopLogic()
    flyer = await make_staged_flyer(logic)
    await flyer.prepare(1)
    logic.stopping = stop
    unstaging = flyer.unstage()
    await asyncio.sleep(0)
    # RE.stop/abort/halt cancel a hanging unstage
    unstaging.task.cancel()
    with pytest.raises((ValueError, asyncio.CancelledError)):
        await unstaging

    logic.stopping = ""
    await flyer.stage()
    await flyer.prepare(2)
    await flyer.kickoff()
    await flyer.complete()
    await flyer.unstage()
    assert logic.previous_ctxs == [None, None]


# Bug: a failed re-prepare left the flyer prepared with the failed prepare's ctx
async def test_failed_reprepare_leaves_nothing_to_kick_off(recording_flyer):
    logic, flyer = recording_flyer
    await flyer.prepare(1)
    await flyer.kickoff()
    await flyer.complete()
    logic.calls.clear()

    async def fail(name: str, value: int, previous_ctx: None) -> AsyncIterator[None]:
        raise ValueError("bad prepare")
        yield None

    logic.prepare_to_fly = fail  # type: ignore
    with pytest.raises(ValueError, match="bad prepare"):
        await flyer.prepare(2)

    with pytest.raises(TransitionError, match="cannot go to FLYING"):
        await flyer.kickoff()
    assert logic.calls == []


# After a failure every verb but unstage() raises, and the restaged retry is a first
# prepare
@pytest.mark.parametrize("failing", ["first", "later"])
async def test_a_failed_prepare_needs_unstage_and_its_retry_is_a_first_prepare(
    recording_flyer, failing: str
):
    logic, flyer = recording_flyer
    seen: list[Ctx | None] = []
    fail = True

    async def prepare_to_fly(name: str, value: int, previous_ctx: Any):
        seen.append(previous_ctx)
        yield Ctx(value)
        if fail:
            raise ValueError("bad start")

    logic.prepare_to_fly = prepare_to_fly  # type: ignore
    if failing == "later":
        fail = False
        await flyer.prepare(1)
        await flyer.kickoff()
        await flyer.complete()
        fail = True
        seen.clear()
    with pytest.raises(ValueError, match="bad start"):
        await flyer.prepare(1)
    fail = False
    with pytest.raises(TransitionError, match="PREPARING from ERROR"):
        await flyer.prepare(1)
    with pytest.raises(TransitionError, match="cannot go to FLYING from ERROR"):
        await flyer.kickoff()
    with pytest.raises(TransitionError, match="cannot go to STAGING from ERROR"):
        await flyer.stage()
    await flyer.unstage()
    await flyer.stage()
    await flyer.prepare(1)

    # The retry is given no context, not that of a prepare before the failed one
    assert seen[-1] is None


async def test_complete_returns_the_fly_status_after_unstage(recording_flyer):
    _, flyer = recording_flyer
    await flyer.prepare(1)
    await flyer.kickoff()
    status = flyer.complete()
    await status

    await flyer.unstage()

    assert flyer.complete() is status


async def _raise_before_kicked_off(ctx: None) -> AsyncIterator[Any]:
    raise ValueError("bad kickoff")
    yield KICKED_OFF


async def _yield_an_update_first(ctx: None) -> AsyncIterator[Any]:
    yield WatcherUpdate(current=0, initial=0, target=1)


async def _finish_without_kicking_off(ctx: None) -> AsyncIterator[Any]:
    return
    yield KICKED_OFF


async def _block_until_cancelled(ctx: None) -> AsyncIterator[Any]:
    await asyncio.Event().wait()
    yield KICKED_OFF


# A kickoff that does not reach KICKED_OFF needs unstage(), and leaves nothing
# running
@pytest.mark.parametrize(
    "fly, error, match",
    [
        (_raise_before_kicked_off, ValueError, "bad kickoff"),
        (_yield_an_update_first, TypeError, "must yield KICKED_OFF first"),
        (_finish_without_kicking_off, RuntimeError, "finished without yielding"),
        (_block_until_cancelled, asyncio.CancelledError, None),
    ],
)
async def test_kickoff_that_does_not_kick_off_needs_unstage(
    recording_flyer, fly, error, match
):
    logic, flyer = recording_flyer
    await flyer.prepare(1)

    logic.fly = fly
    kickoff = flyer.kickoff()
    if error is asyncio.CancelledError:
        # Cancelled directly, not by unstage
        await asyncio.sleep(0)
        kickoff.task.cancel()
    with pytest.raises(error, match=match):
        await kickoff

    with pytest.raises(TransitionError, match="from ERROR"):
        await flyer.kickoff()
    await flyer.unstage()
    await flyer.stage()
    await flyer.prepare(2)


async def test_kickoff_cancelled_just_after_kicked_off_ends_the_fly(recording_flyer):
    logic, flyer = recording_flyer
    await flyer.prepare(1)
    kickoff = flyer.kickoff()
    ended = asyncio.Event()

    async def fly(ctx: None) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        try:
            yield KICKED_OFF
            # An outside cancel (e.g. a timeout) that lands before kickoff resumes
            kickoff.task.cancel()
            await asyncio.Event().wait()
        finally:
            ended.set()

    logic.fly = fly
    with pytest.raises(asyncio.CancelledError):
        await kickoff
    assert ended.is_set()
    with pytest.raises(TransitionError, match="from ERROR"):
        await flyer.kickoff()
    await flyer.unstage()
    await flyer.stage()
    await flyer.prepare(2)


@pytest.mark.parametrize("bad_yield", [42, KICKED_OFF])
async def test_a_non_update_yielded_after_kicked_off_fails_complete(
    recording_flyer, bad_yield
):
    logic, flyer = recording_flyer

    async def fly(ctx: None) -> AsyncIterator[Any]:
        yield KICKED_OFF
        yield bad_yield

    logic.fly = fly
    await flyer.prepare(1)
    await flyer.kickoff()
    with pytest.raises(TypeError, match=r"\.fly\(\) must yield only WatcherUpdates"):
        await flyer.complete()


# A complete() that does not succeed ends the fly and needs unstage(), whether it
# is cancelled directly (not via unstage) or fly raises after kickoff
@pytest.mark.parametrize("fail", [False, True])
async def test_unsuccessful_complete_cancels_the_fly_and_needs_unstage(fail):
    logic = FlyingLogic(fail=fail)
    flyer = await make_staged_flyer(logic)
    await flyer.prepare(1)
    await flyer.kickoff()
    completing = flyer.complete()

    if fail:
        with pytest.raises(ValueError, match="bad fly"):
            await completing
    else:
        await asyncio.sleep(0)
        assert not logic.fly_statuses[0].done
        completing.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await completing

    assert logic.fly_statuses[0].task.cancelled()
    # complete() still returns the failed fly, but it cannot be kicked off again
    assert flyer.complete() is completing
    with pytest.raises(TransitionError, match="cannot go to FLYING from ERROR"):
        await flyer.kickoff()
    # Restaged and prepared again, it can fly again
    logic.fail = False
    await flyer.unstage()
    await flyer.stage()
    await flyer.prepare(2)
    await flyer.kickoff()
    await flyer.unstage()


def test_logic_that_is_also_movable_may_define_stop_with_a_deprecation():
    with pytest.deprecated_call(match=r"CombinedLogic.stop\(\) is deprecated"):

        class CombinedLogic(MovableLogic[float], FlyableLogic[None]):
            async def stop(self) -> None: ...

    assert CombinedLogic.ensure_stopped is CombinedLogic.stop


@dataclass
class FailingCleanupLogic(RecordingFlyableLogic):
    """Its fly raises while it is being cancelled, `block_kickoff` or not."""

    block_kickoff: bool = False
    #: Fail on its own just after kicking off, rather than when cancelled
    raise_after_kickoff: bool = False

    async def fly(self, ctx: None) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        try:
            if self.block_kickoff:
                await asyncio.Event().wait()
            yield KICKED_OFF
            if not self.raise_after_kickoff:
                await asyncio.Event().wait()
        finally:
            raise ValueError("cleanup failed")  # noqa: B012


# A cancelled kickoff() reports its cancel; complete() is the fly, so reports
# the failure of the fly's cleanup
@pytest.mark.parametrize(
    "phase, error",
    [
        ("kickoff", asyncio.CancelledError),
        ("complete", ValueError),
    ],
)
async def test_failing_fly_cleanup_when_kickoff_or_complete_is_cancelled(
    phase: str, error: type[BaseException]
):
    logic = FailingCleanupLogic(block_kickoff=phase == "kickoff")
    flyer = await make_staged_flyer(logic)
    await flyer.prepare(1)
    status = flyer.kickoff()
    if phase == "complete":
        await status
        status = flyer.complete()
    await asyncio.sleep(0)
    status.task.cancel()

    with pytest.raises(error):
        await status
    # Ready to be prepared once restaged
    await flyer.unstage()
    await flyer.stage()
    await flyer.prepare(2)


async def test_unstage_stops_the_hardware_then_raises_the_fly_failure():
    # The fly fails while being cancelled
    logic = FailingCleanupLogic()
    flyer = await make_staged_flyer(logic)
    await flyer.prepare(1)
    await flyer.kickoff()
    await asyncio.sleep(0)
    logic.calls.clear()

    with pytest.raises(ValueError, match="cleanup failed"):
        await flyer.unstage()

    assert logic.calls == ["ensure_stopped"]
    # Unstaged all the same
    await flyer.stage()


class FailsToUnstage(Device):
    @AsyncStatus.wrap
    async def stage(self) -> None: ...

    @AsyncStatus.wrap
    async def unstage(self) -> None:
        raise ValueError("unstage failed")


@dataclass
class HangingStopLogic(RecordingFlyableLogic):
    """Once `hang` is set, its `ensure_stopped` runs until cancelled."""

    hang: bool = False
    stopping: bool = False

    async def ensure_stopped(self) -> None:
        self.stopping = self.hang
        try:
            if self.hang:
                await asyncio.Event().wait()
        finally:
            self.stopping = False


async def test_unstage_that_fails_leaves_no_other_hook_running():
    logic = HangingStopLogic()

    class ReadableFlyer(StandardReadable, StandardFlyable[int, None]):
        def __init__(self, name: str = ""):
            with self.add_children_as_readables():
                self.child = FailsToUnstage()
            super().__init__(name=name)

        @cached_property
        def logic(self) -> FlyableLogic[int, None]:
            return logic

    async with init_devices(mock=True):
        device = ReadableFlyer(name="rf")
    await device.stage()
    logic.hang = True

    with pytest.raises(ValueError, match="unstage failed"):
        await device.unstage()

    assert not logic.stopping


class FailsToStage(Device):
    @AsyncStatus.wrap
    async def stage(self) -> None:
        raise ValueError("stage failed")

    @AsyncStatus.wrap
    async def unstage(self) -> None: ...


@dataclass
class HangingReadyLogic(RecordingFlyableLogic):
    """Its `ensure_ready` runs until cancelled."""

    readying: bool = False

    async def ensure_ready(self) -> None:
        self.readying = True
        try:
            await asyncio.Event().wait()
        finally:
            self.readying = False


async def test_stage_that_fails_leaves_no_other_hook_running():
    logic = HangingReadyLogic()

    class ReadableFlyer(StandardReadable, StandardFlyable[int, None]):
        def __init__(self, name: str = ""):
            with self.add_children_as_readables():
                self.child = FailsToStage()
            super().__init__(name=name)

        @cached_property
        def logic(self) -> FlyableLogic[int, None]:
            return logic

    async with init_devices(mock=True):
        device = ReadableFlyer(name="rf")

    with pytest.raises(ValueError, match="stage failed"):
        await device.stage()

    assert not logic.readying


@dataclass
class SlowToCancelLogic(RecordingFlyableLogic):
    """Its verbs take a moment to finish being cancelled."""

    block: str = ""
    running: set[str] = field(default_factory=set)
    running_when_stopped: list[set[str]] = field(default_factory=list)

    async def _block(self, verb: str) -> None:
        if self.block != verb:
            return
        self.running.add(verb)
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.05)
            self.running.discard(verb)

    async def prepare_to_fly(
        self, name: str, value: int, previous_ctx: None
    ) -> AsyncGenerator[None, None]:
        await self._block("prepare")
        yield None

    async def fly(self, ctx: None) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
        await self._block("kickoff")
        yield KICKED_OFF

    async def ensure_stopped(self) -> None:
        self.running_when_stopped.append(set(self.running))


@pytest.mark.parametrize("verb", ["prepare", "kickoff"])
async def test_unstage_waits_for_the_cancelled_verb_before_stopping(verb: str):
    logic = SlowToCancelLogic(block=verb)
    flyer = await make_staged_flyer(logic)
    logic.running_when_stopped.clear()
    if verb == "prepare":
        running = flyer.prepare(1)
    else:
        await flyer.prepare(1)
        running = flyer.kickoff()
    await wait_for_pending_wakeups()
    assert logic.running == {verb}

    await flyer.unstage()

    assert logic.running == set()
    assert logic.running_when_stopped == [set()]
    with pytest.raises(asyncio.CancelledError):
        await running


@pytest.mark.parametrize(
    "eager",
    [
        False,
        pytest.param(
            True,
            marks=pytest.mark.skipif(
                sys.version_info < (3, 12), reason="eager_task_factory is 3.12+"
            ),
        ),
    ],
)
async def test_complete_starts_with_the_latest_update_fly_yielded_before_it(
    eager: bool,
):
    if eager:
        loop = asyncio.get_running_loop()
        loop.set_task_factory(asyncio.eager_task_factory)  # pyright: ignore
    release = asyncio.Event()

    class UpdatingLogic(RecordingFlyableLogic):
        async def fly(
            self, ctx: None
        ) -> AsyncGenerator[KICKED_OFF | WatcherUpdate, None]:
            yield KICKED_OFF
            yield WatcherUpdate(current=1, initial=0, target=3)
            yield WatcherUpdate(current=2, initial=0, target=3)
            await release.wait()
            yield WatcherUpdate(current=3, initial=0, target=3)

    flyer = await make_staged_flyer(UpdatingLogic())
    await flyer.prepare(1)
    await flyer.kickoff()
    await asyncio.sleep(0.01)

    watcher = Mock()
    status = flyer.complete()
    status.watch(watcher)
    await asyncio.sleep(0.01)
    release.set()
    await status

    assert [c.kwargs["current"] for c in watcher.call_args_list] == [2, 3]
    # complete() is the fly's own status, however often it is called
    assert flyer.complete() is status


@dataclass
class RunUpLogic(RecordingFlyableLogic):
    """Its prepare_to_fly runs up until cancelled, or fails part way if `fail`."""

    fail: bool = False
    run_ups: list[AsyncStatus] = field(default_factory=list)
    closed: bool = False

    async def prepare_to_fly(
        self, name: str, value: int, previous_ctx: None
    ) -> AsyncGenerator[Any, None]:
        yield value
        try:
            async with AsyncStatus(asyncio.Event().wait()) as run_up:
                self.run_ups.append(run_up)
                yield WatcherUpdate(current=0, initial=0, target=1)
                if self.fail:
                    raise ValueError("bad run-up")
                await run_up
        finally:
            self.closed = True


@pytest.mark.parametrize("fail", [False, True])
async def test_prepare_that_fails_or_is_cancelled_stops_the_run_up(fail: bool):
    logic = RunUpLogic(fail=fail)
    flyer = await make_staged_flyer(logic)
    preparing = flyer.prepare(1)
    await wait_for_pending_wakeups()

    if fail:
        with pytest.raises(ValueError, match="bad run-up"):
            await preparing
    else:
        assert not logic.closed
        preparing.task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await preparing

    # The generator was closed and the run-up stopped before prepare() finished
    assert logic.closed
    assert logic.run_ups[0].task.cancelled()
    # The half-failed prepare left nothing to fly
    with pytest.raises(TransitionError, match="cannot go to FLYING from ERROR"):
        await flyer.kickoff()


async def _update_first(
    name: str, value: int, previous_ctx: None
) -> AsyncIterator[Any]:
    yield WatcherUpdate(current=0, initial=0, target=1)


async def _no_ctx(name: str, value: int, previous_ctx: None) -> AsyncIterator[Any]:
    return
    yield


async def _ctx_then_not_an_update(
    name: str, value: int, previous_ctx: None
) -> AsyncIterator[Any]:
    yield value
    yield 42


@pytest.mark.parametrize(
    "prepare_to_fly, error, match",
    [
        (
            _update_first,
            TypeError,
            r"\.prepare_to_fly\(\) must yield its context first",
        ),
        (_no_ctx, RuntimeError, "finished without yielding its context"),
        (
            _ctx_then_not_an_update,
            TypeError,
            r"\.prepare_to_fly\(\) must yield only WatcherUpdates",
        ),
    ],
)
async def test_prepare_to_fly_that_does_not_yield_its_context_first_raises(
    recording_flyer, prepare_to_fly, error, match
):
    logic, flyer = recording_flyer
    logic.prepare_to_fly = prepare_to_fly

    with pytest.raises(error, match=match):
        await flyer.prepare(1)
    with pytest.raises(TransitionError, match="cannot go to FLYING from ERROR"):
        await flyer.kickoff()


async def test_a_fly_that_fails_and_is_completed_is_not_logged(
    caplog: pytest.LogCaptureFixture,
):
    flyer = await make_staged_flyer(FlyingLogic(fail=True))
    await flyer.prepare(1)
    await flyer.kickoff()
    with pytest.raises(ValueError, match="bad fly"):
        await flyer.complete()

    await flyer.unstage()

    assert not caplog.records
