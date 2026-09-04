"""Type-level regression tests for the status classes.

The failure mode these guard against is a status losing its type parameter and
silently degrading to `Any`, which type-checks clean by construction -- so the
assertions have to be `assert_type` under pyright rather than runtime asserts.
That makes checking this file a requirement, not a nicety: it is listed by name
in the `type-checking` tox env. `assert_type` itself is a no-op at runtime, so
each test also exercises the behaviour it is describing.
"""

from collections.abc import AsyncIterator
from typing import assert_type

from ophyd_async.core import (
    AsyncStatus,
    Device,
    WatchableAsyncStatus,
    WatcherUpdate,
)


async def test_async_status_result_type_survives_construction() -> None:
    async def make_int() -> int:
        return 3

    status = AsyncStatus(make_int())
    assert_type(status, AsyncStatus[int])
    await status
    assert_type(status.result(), int)
    assert status.result() == 3


async def test_async_status_result_type_survives_wrap() -> None:
    # `wrap` is *the* way devices produce statuses, so it is the path that decides
    # whether bluesky's `StatusWithResult[R]` means anything for a real device.
    class IntDevice(Device):
        @AsyncStatus.wrap
        async def get_int(self, value: int) -> int:
            return value

    status = IntDevice().get_int(3)
    assert_type(status, AsyncStatus[int])
    await status
    assert_type(status.result(), int)
    assert status.result() == 3


async def test_watchable_async_status_reports_watch_type_not_result_type() -> None:
    # A watchable status is parametrised by what it reports to watchers, and its
    # result is always None: it is built from an async generator, and those cannot
    # return a value at all.
    class FloatDevice(Device):
        @WatchableAsyncStatus.wrap
        async def set(self, value: float) -> AsyncIterator[WatcherUpdate[float]]:
            yield WatcherUpdate(initial=0.0, current=value, target=value)

    currents: list[float | None] = []

    def watcher(
        current: float | None = None,
        initial: float | None = None,
        target: float | None = None,
        name: str | None = None,
        unit: str | None = None,
        precision: int | None = None,
        fraction: float | None = None,
        time_elapsed: float | None = None,
        time_remaining: float | None = None,
    ) -> None:
        currents.append(current)

    status = FloatDevice().set(1.5)
    assert_type(status, WatchableAsyncStatus[float])
    # `watch` takes a `Watcher[float]`, so a watcher of the wrong value type is
    # now rejected rather than silently accepted
    status.watch(watcher)
    await status
    assert_type(status.result(), None)
    assert status.result() is None
    assert currents == [1.5]
