import asyncio
from collections.abc import AsyncIterator
from functools import partial

import bluesky.plan_stubs as bps
import pytest
from bluesky.protocols import Movable

from ophyd_async.core import (
    AsyncStatus,
    StandardReadable,
    WatchableAsyncStatus,
    WatcherUpdate,
    soft_signal_r_and_setter,
)


class SetFailed(Exception):
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
        raise asyncio.TimeoutError()


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
            raise SetFailed
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
    assert isinstance(st.exception(), SetFailed)
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
