"""Equivalent of bluesky.protocols.Status for asynchronous tasks."""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from dataclasses import asdict, replace
from typing import Generic

from bluesky.protocols import Status

from ._device import Device
from ._protocol import Watcher
from ._utils import Callback, P, T, WatcherUpdate


class AsyncStatusBase(Status, Awaitable[None]):
    """Convert asyncio awaitable to bluesky Status interface."""

    def __init__(self, awaitable: Coroutine | asyncio.Task, name: str | None = None):
        if isinstance(awaitable, asyncio.Task):
            self.task = awaitable
        else:
            self.task = asyncio.create_task(awaitable)
        self.task.add_done_callback(self._run_callbacks)
        self._callbacks: list[Callback[Status]] = []
        self._name = name

    def __await__(self):
        return self.task.__await__()

    def add_callback(self, callback: Callback[Status]):
        if self.done:
            callback(self)
        else:
            self._callbacks.append(callback)

    def _run_callbacks(self, task: asyncio.Task):
        for callback in self._callbacks:
            callback(self)

    def exception(self, timeout: float | None = 0.0) -> BaseException | None:
        """Return any exception raised by the task.

        :param timeout:
            Taken for compatibility with the Status interface, but must be 0.0 as we
            cannot wait for an async function in a sync call.
        """
        if timeout != 0.0:
            raise ValueError(
                "cannot honour any timeout other than 0 in an asynchronous function"
            )
        if self.task.done():
            try:
                return self.task.exception()
            except asyncio.CancelledError as e:
                return e
        return None

    @property
    def done(self) -> bool:
        return self.task.done()

    @property
    def success(self) -> bool:
        return (
            self.task.done()
            and not self.task.cancelled()
            and self.task.exception() is None
        )

    def __repr__(self) -> str:
        if self.done:
            if e := self.exception():
                status = f"errored: {repr(e)}"
            else:
                status = "done"
        else:
            status = "pending"
        device_str = f"device: {self._name}, " if self._name else ""
        return (
            f"<{type(self).__name__}, {device_str}"
            f"task: {self.task.get_coro()}, {status}>"
        )

    __str__ = __repr__


class AsyncStatus(AsyncStatusBase):
    """Convert an asyncio awaitable to bluesky Status interface.

    :param awaitable: The coroutine or task to await.
    :param name: The name of the device, if available.

    For example:
    ```python
    status = AsyncStatus(asyncio.sleep(1))
    assert not status.done
    await status # waits for 1 second
    assert status.done
    ```
    """

    @classmethod
    def wrap(cls, f: Callable[P, Coroutine]) -> Callable[P, AsyncStatus]:
        """Wrap an async function in an AsyncStatus and return it.

        Used to make an async function conform to a bluesky protocol.

        For example:
        ```python
        class MyDevice(Device):
            @AsyncStatus.wrap
            async def trigger(self):
                await asyncio.sleep(1)
        ```
        """

        @functools.wraps(f)
        def wrap_f(*args: P.args, **kwargs: P.kwargs) -> AsyncStatus:
            if args and isinstance(args[0], Device):
                name = args[0].name
            else:
                name = None
            return cls(f(*args, **kwargs), name=name)

        return wrap_f


class WatchableAsyncStatus(AsyncStatusBase, Generic[T]):
    """Convert an asyncio async iterable to bluesky Status and Watcher interface.

    :param iterator: The async iterable to await.
    :param name: The name of the device, if available.
    """

    def __init__(
        self, iterator: AsyncIterator[WatcherUpdate[T]], name: str | None = None
    ):
        self._watchers: list[Watcher] = []
        self._start = time.monotonic()
        self._last_update: WatcherUpdate[T] | None = None
        super().__init__(self._notify_watchers_from(iterator), name)

    async def _notify_watchers_from(self, iterator: AsyncIterator[WatcherUpdate[T]]):
        async for update in iterator:
            self._last_update = (
                update
                if update.time_elapsed is not None
                else replace(update, time_elapsed=time.monotonic() - self._start)
            )
            for watcher in self._watchers:
                self._update_watcher(watcher, self._last_update)

    def _update_watcher(self, watcher: Watcher, update: WatcherUpdate[T]):
        vals = asdict(
            update, dict_factory=lambda d: {k: v for k, v in d if v is not None}
        )
        watcher(**vals)

    def watch(self, watcher: Watcher):
        """Add a watcher to the status.

        It is called:
        - immediately if there has already been an update
        - on every subsequent update
        """
        self._watchers.append(watcher)
        if self._last_update:
            self._update_watcher(watcher, self._last_update)

    @classmethod
    def wrap(
        cls,
        f: Callable[P, AsyncIterator[WatcherUpdate[T]]],
    ) -> Callable[P, WatchableAsyncStatus[T]]:
        """Wrap an AsyncIterator in a WatchableAsyncStatus.

        For example:
        ```python
        class MyDevice(Device):
            @WatchableAsyncStatus.wrap
            async def trigger(self):
                # sleep for a second, updating on progress every 0.1 seconds
                for i in range(10):
                    yield WatcherUpdate(initial=0, current=i*0.1, target=1)
                    await asyncio.sleep(0.1)
        ```
        """

        @functools.wraps(f)
        def wrap_f(*args: P.args, **kwargs: P.kwargs) -> WatchableAsyncStatus[T]:
            if args and isinstance(args[0], Device):
                name = args[0].name
            else:
                name = None
            return cls(f(*args, **kwargs), name=name)

        return wrap_f


@AsyncStatus.wrap
async def completed_status(exception: Exception | None = None):
    """Return a completed AsyncStatus.

    :param exception: If given, then raise this exception when awaited.
    """
    if exception:
        raise exception
    return None
