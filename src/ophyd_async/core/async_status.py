"""Equivalent of bluesky.protols.Status for asynchronous tasks."""

import asyncio
import functools
from typing import Awaitable, Callable, Coroutine, List, Optional, cast

from bluesky.protocols import Status

from .utils import Callback, T


class AsyncStatus(Status):
    """Convert asyncio awaitable to bluesky Status interface"""

    def __init__(
        self,
        awaitable: Awaitable,
        watchers: Optional[List[Callable]] = None,
    ):
        if isinstance(awaitable, asyncio.Task):
            self.task = awaitable
        else:
            self.task = asyncio.create_task(awaitable)  # type: ignore
        self.task.add_done_callback(self._run_callbacks)
        self._callbacks = cast(List[Callback[Status]], [])
        self._watchers = watchers

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

    # TODO: remove ignore and bump min version when bluesky v1.12.0 is released
    def exception(  # type: ignore
        self, timeout: Optional[float] = 0.0
    ) -> Optional[BaseException]:
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
            self.task.done() and not self.task.cancelled() and not self.task.exception()
        )

    def watch(self, watcher: Callable):
        """Add watcher to the list of interested parties.

        Arguments as per Bluesky :external+bluesky:meth:`watch` protocol.
        """
        if self._watchers is not None:
            self._watchers.append(watcher)

    @classmethod
    def wrap(cls, f: Callable[[T], Coroutine]) -> Callable[[T], "AsyncStatus"]:
        @functools.wraps(f)
        def wrap_f(self) -> AsyncStatus:
            return AsyncStatus(f(self))

        return wrap_f

    def __repr__(self) -> str:
        if self.done:
            if self.exception() is not None:
                status = "errored"
            else:
                status = "done"
        else:
            status = "pending"
        return f"<{type(self).__name__} {status}>"

    __str__ = __repr__
