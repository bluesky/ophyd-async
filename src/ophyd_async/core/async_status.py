"""Equivalent of bluesky.protocols.Status for asynchronous tasks."""

import asyncio
import functools
import time
from dataclasses import replace
from typing import AsyncIterator, Awaitable, Callable, Generic, Type, TypeVar, cast

from bluesky.protocols import Status

from .utils import Callback, P, T, Watcher, WatcherUpdate

AS = TypeVar("AS")


class AsyncStatusBase(Status):
    """Convert asyncio awaitable to bluesky Status interface"""

    def __init__(
        self,
        awaitable: Awaitable,
    ):
        if isinstance(awaitable, asyncio.Task):
            self.task = awaitable
        else:
            self.task = asyncio.create_task(awaitable)  # type: ignore
        self.task.add_done_callback(self._run_callbacks)
        self._callbacks = cast(list[Callback[Status]], [])

    def __await__(self):
        return self.task.__await__()

    def add_callback(self, callback: Callback[Status]):
        if self.done:
            callback(self)
        else:
            self._callbacks.append(callback)

    def _run_callbacks(self, task: asyncio.Task):
        if not task.cancelled():
            for callback in self._callbacks:
                callback(self)

    def exception(self, timeout: float | None = 0.0) -> BaseException | None:
        if timeout != 0.0:
            raise Exception(
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
        return f"<{type(self).__name__}, task: {self.task.get_coro()}, {status}>"

    __str__ = __repr__


class AsyncStatus(AsyncStatusBase):
    @classmethod
    def wrap(cls: Type[AS], f: Callable[P, Awaitable]) -> Callable[P, AS]:
        @functools.wraps(f)
        def wrap_f(*args: P.args, **kwargs: P.kwargs) -> AS:
            return cls(f(*args, **kwargs))

        # type is actually functools._Wrapped[P, Awaitable, P, AS]
        # but functools._Wrapped is not necessarily available
        return cast(Callable[P, AS], wrap_f)


class WatchableAsyncStatus(AsyncStatusBase, Generic[T]):
    """Convert AsyncIterator of WatcherUpdates to bluesky Status interface."""

    def __init__(self, iterator: AsyncIterator[WatcherUpdate[T]]):
        self._watchers: list[Watcher]
        self._start = time.monotonic()
        self._last_update: WatcherUpdate[T] | None = None
        super().__init__(self._notify_watchers_from(iterator))

    async def _notify_watchers_from(self, iterator: AsyncIterator[WatcherUpdate[T]]):
        async for self._last_update in iterator:
            for watcher in self._watchers:
                self._update_watcher(watcher, self._last_update)

    def _update_watcher(self, watcher: Watcher, update: WatcherUpdate[T]):
        watcher(replace(update, time_elapsed_s=time.monotonic() - self._start))

    def watch(self, watcher: Watcher):
        self._watchers.append(watcher)
        if self._last_update:
            self._update_watcher(watcher, self._last_update)

    @classmethod
    def wrap(
        cls: Type[AS], f: Callable[P, AsyncIterator[WatcherUpdate[T]]]
    ) -> Callable[P, AS]:
        @functools.wraps(f)
        def wrap_f(*args: P.args, **kwargs: P.kwargs) -> AS:
            return cls(f(*args, **kwargs))

        return cast(Callable[P, AS], wrap_f)
