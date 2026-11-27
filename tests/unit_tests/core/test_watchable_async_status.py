import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from functools import partial

import bluesky.plan_stubs as bps
import pytest
from bluesky.protocols import Movable
from bluesky.utils import FailedStatus

from ophyd_async.core import (
    AsyncStatus,
    Device,
    StandardReadable,
    WatchableAsyncStatus,
    WatcherUpdate,
    soft_signal_r_and_setter,
)
from ophyd_async.testing import wait_for_pending_wakeups


class SetFailedError(Exception):
    pass


def watcher_test(
    storage: list[WatcherUpdate],
    *,
    name: str | None,
    current: int | None,
    initial: int | None,
    target: int | None,
    unit: str | None,
    precision: float | None,
    fraction: float | None,
    time_elapsed: float | None,
    time_remaining: float | None,
):
    storage.append(
        WatcherUpdate(
            name=name,
            current=current,
            initial=initial,
            target=target,
            unit=unit,
            precision=precision,
            fraction=fraction,
            time_elapsed=time_elapsed,
            time_remaining=time_remaining,
        )
    )


class TWatcher:
    updates: list[int] = []

    def __call__(
        self,
        *,
        name: str | None,
        current: int | None,
        initial: int | None,
        target: int | None,
        unit: str | None,
        precision: float | None,
        fraction: float | None,
        time_elapsed: float | None,
        time_remaining: float | None,
    ) -> None:
        self.updates.append(current or -1)


class ASTestDevice(StandardReadable, Movable):
    def __init__(self, name: str = "") -> None:
        self._staged: bool = False
        self.sig, self._sig_setter = soft_signal_r_and_setter(datatype=int)
        super().__init__(name)

    @AsyncStatus.wrap
    async def stage(self):
        self._staged = True
        await asyncio.sleep(0.01)


class ASTestDeviceSingleSet(ASTestDevice):
    @AsyncStatus.wrap
    async def set(self, val):
        assert self._staged
        await asyncio.sleep(0.01)
        self._sig_setter(val)  # type: ignore


class ASTestDeviceTimeoutSet(ASTestDevice):
    @WatchableAsyncStatus.wrap
    async def set(self, val, timeout=0.01):
        await asyncio.sleep(timeout)
        yield WatcherUpdate(1, 1, 1)
        raise TimeoutError()


class ASTestDeviceIteratorSet(ASTestDevice):
    def __init__(
        self, name: str = "", values=(1, 2, 3, 4, 5), complete_set: bool = True
    ) -> None:
        self.values = values
        self.complete_set = complete_set
        super().__init__(name)

    @WatchableAsyncStatus.wrap
    async def set(self, val) -> AsyncIterator:
        assert self._staged
        self._initial = await self.sig.get_value()
        for point in self.values:
            await asyncio.sleep(0.01)
            yield WatcherUpdate(
                name=self.name,
                current=point,
                initial=self._initial,
                target=val,
                unit="dimensionless",
                precision=0.0,
                time_elapsed=0,
                time_remaining=0,
                fraction=0,
            )
        if self.complete_set:
            self._sig_setter(val)  # type: ignore
            yield WatcherUpdate(
                name=self.name,
                current=val,
                initial=self._initial,
                target=val,
                unit="dimensionless",
                precision=0.0,
                time_elapsed=0,
                time_remaining=0,
                fraction=0,
            )
        else:
            raise SetFailedError
        return


async def test_asyncstatus_wraps_both_stage_and_set(RE):
    td = ASTestDeviceSingleSet()
    await td.connect()
    with pytest.raises(AssertionError):
        st = td.set(5)
        assert isinstance(st, AsyncStatus)
        await st
    await td.stage()
    st = td.set(5)
    assert isinstance(st, AsyncStatus)
    await st
    assert (await td.sig.get_value()) == 5
    RE(bps.abs_set(td, 3, wait=True))
    assert (await td.sig.get_value()) == 3


async def test_asyncstatus_wraps_set_iterator_with_class_or_func_watcher(RE):
    td = ASTestDeviceIteratorSet()
    await td.connect()
    await td.stage()
    st = td.set(6)
    updates = []

    w = TWatcher()
    st.watch(partial(watcher_test, updates))
    st.watch(w)
    await st
    assert st.done
    assert st.success
    assert len(updates) == 6
    assert sum(w.updates) == 21


async def test_watchableasyncstatus_wraps_failing_set_iterator(RE):
    td = ASTestDeviceIteratorSet(values=[1, 2, 3], complete_set=False)
    await td.connect()
    await td.stage()
    st = td.set(6)
    updates = []

    st.watch(partial(watcher_test, updates))
    try:
        await st
    except Exception:
        ...
    assert st.done
    assert not st.success
    assert isinstance(st.exception(), SetFailedError)
    assert len(updates) == 3


async def test_watchableasyncstatus_times_out(RE):
    td = ASTestDeviceTimeoutSet()
    await td.connect()
    await td.stage()
    st = td.set(6, timeout=0.01)
    while not st.done:
        await asyncio.sleep(0.01)
    assert not st.success
    assert isinstance(st.exception(), asyncio.TimeoutError)


async def test_device_name_in_failure_message_watchableasyncstatus_wrap(RE):
    class FailingWatchableMovable(Movable, Device):
        @WatchableAsyncStatus.wrap
        async def set(self, value) -> AsyncIterator:
            yield WatcherUpdate(0, 0, value)
            raise ValueError("This doesn't work")

    device_name = "MyFailingMovable"
    d = FailingWatchableMovable(name=device_name)
    with pytest.raises(FailedStatus) as ctx:
        RE(bps.mv(d, 3))
    # FailingMovable.set is decorated with @AsyncStatus.wrap
    # undecorated methods will not print the device name
    status: AsyncStatus = ctx.value.args[0]
    assert f"device: {device_name}" in repr(status)


class StopError(Exception):
    pass


class Ticks:
    """Yields an update then waits forever, or until `finish` is resolved."""

    def __init__(self, finish: asyncio.Future | None = None):
        self.finish = finish
        self.started = False

    async def run(self) -> AsyncGenerator[WatcherUpdate[int], None]:
        self.started = True
        yield WatcherUpdate(current=1, initial=0, target=2)
        await (self.finish or asyncio.Future())


@pytest.mark.parametrize("error", [None, StopError("stopped")])
@pytest.mark.parametrize("before_start", [True, False])
async def test_stop_future_ends_a_watchable_status(error, before_start):
    ticks = Ticks()
    stop = asyncio.get_running_loop().create_future()
    updates: list[dict] = []
    if before_start:
        stop.set_result(error)
    status = WatchableAsyncStatus(ticks.run(), stop=stop)
    status.watch(lambda **kw: updates.append(kw))
    if not before_start:
        await wait_for_pending_wakeups()
        assert not status.done
        stop.set_result(error)
    if error is None:
        await status
        assert status.success
    else:
        with pytest.raises(StopError):
            await status
    # Stopped before it started, so the iterator body never ran
    assert ticks.started is not before_start
    assert len(updates) == (0 if before_start else 1)


async def test_no_stop_future_adds_nothing():
    tasks = asyncio.all_tasks()
    finish = asyncio.get_running_loop().create_future()
    status = WatchableAsyncStatus(Ticks(finish).run())
    await wait_for_pending_wakeups()
    assert asyncio.all_tasks() - tasks == {status.task}
    finish.set_result(None)
    await status


@pytest.mark.parametrize("stop_first", [True, False])
async def test_outside_cancel_with_stop_in_the_same_iteration_cancels(stop_first):
    stop = asyncio.get_running_loop().create_future()
    status = WatchableAsyncStatus(Ticks().run(), stop=stop)
    await wait_for_pending_wakeups()
    if stop_first:
        stop.set_result(None)
        status.task.cancel()
    else:
        status.task.cancel()
        stop.set_result(None)
    with pytest.raises(asyncio.CancelledError):
        await status
    assert status.task.cancelled()


@pytest.mark.parametrize("yields", range(5))
async def test_outside_cancel_while_the_iterator_is_finishing_is_not_lost(yields):
    loop = asyncio.get_running_loop()
    finish, stop = loop.create_future(), loop.create_future()
    ticks = Ticks(finish)
    status = WatchableAsyncStatus(ticks.run(), stop=stop)
    await wait_for_pending_wakeups()
    finish.set_result(None)
    for _ in range(yields):
        await asyncio.sleep(0)
    if status.task.cancel():
        with pytest.raises(asyncio.CancelledError):
            await status
        assert status.task.cancelled()
    else:
        await status


async def test_timeout_inside_a_stoppable_watchable_status_raises_timeout_error():
    async def iterator():
        async with asyncio.timeout(0):
            yield WatcherUpdate(current=1, initial=0, target=2)
            await asyncio.Future()

    stop = asyncio.get_running_loop().create_future()
    status = WatchableAsyncStatus(iterator(), stop=stop)
    with pytest.raises(TimeoutError):
        await status


async def test_stop_future_decides_even_if_the_iterator_absorbs_the_cancel():
    async def iterator():
        yield WatcherUpdate(current=1, initial=0, target=2)
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            pass

    stop = asyncio.get_running_loop().create_future()
    status = WatchableAsyncStatus(iterator(), stop=stop)
    await wait_for_pending_wakeups()
    stop.set_result(StopError("stopped"))
    with pytest.raises(StopError):
        await status


class MoveError(Exception):
    pass


@pytest.mark.parametrize("error", [None, MoveError("failed")])
async def test_an_iterator_ending_in_the_same_iteration_as_the_stop_wins(error):
    loop = asyncio.get_running_loop()
    finish, stop = loop.create_future(), loop.create_future()

    async def iterator():
        yield WatcherUpdate(current=1, initial=0, target=2)
        await finish
        if error:
            raise error

    status = WatchableAsyncStatus(iterator(), stop=stop)
    await wait_for_pending_wakeups()
    finish.set_result(None)
    # The iterator resumes before the stop resolves, so both are done by the
    # time the race looks
    stop.set_result(StopError("stopped"))
    if error:
        with pytest.raises(MoveError):
            await status
    else:
        await status


async def test_an_error_raised_while_stopping_shows_through():
    async def iterator():
        yield WatcherUpdate(current=1, initial=0, target=2)
        try:
            await asyncio.Future()
        except asyncio.CancelledError as e:
            raise MoveError("failed to stop") from e

    stop = asyncio.get_running_loop().create_future()
    status = WatchableAsyncStatus(iterator(), stop=stop)
    await wait_for_pending_wakeups()
    stop.set_result(StopError("stopped"))
    with pytest.raises(MoveError):
        await status


async def test_a_second_outside_cancel_waits_for_the_iterator_cleanup():
    release = asyncio.Event()
    cleaned_up = False

    async def iterator():
        nonlocal cleaned_up
        try:
            yield WatcherUpdate(current=1, initial=0, target=2)
            await asyncio.Future()
        finally:
            # Slow cleanup, which a second cancel must not abandon
            await release.wait()
            cleaned_up = True

    stop = asyncio.get_running_loop().create_future()
    status = WatchableAsyncStatus(iterator(), stop=stop)
    await wait_for_pending_wakeups()
    status.task.cancel()
    await wait_for_pending_wakeups()
    status.task.cancel()
    await wait_for_pending_wakeups()
    assert not status.done
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await status
    assert cleaned_up
