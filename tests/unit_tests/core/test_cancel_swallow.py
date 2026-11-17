import asyncio
from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import Mock

import pytest

from ophyd_async.core import AsyncStatus, soft_signal_rw

# The waits these cleanups cancel are internal, with no public way to slow them down
from ophyd_async.core import _signal as signal_module  # noqa: PLC2701
from ophyd_async.sim._blob_acquire_logic import BlobAcquireLogic  # noqa: PLC2701


def _slow_to_cancel(cancelling: asyncio.Event):
    """A coroutine that takes a moment to finish cancelling, like async cleanup."""

    async def coro():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelling.set()
            await asyncio.sleep(0.2)
            raise

    return coro()


async def _status_aexit(cancelling: asyncio.Event, _: pytest.MonkeyPatch):
    async with AsyncStatus(_slow_to_cancel(cancelling)):
        await asyncio.sleep(0)  # let the status task start


async def _blob_ensure_stopped(cancelling: asyncio.Event, _: pytest.MonkeyPatch):
    pattern_generator = Mock()
    pattern_generator.write_images_to_file = lambda: _slow_to_cancel(cancelling)
    logic = BlobAcquireLogic(pattern_generator)
    await logic.start_acquiring()
    await asyncio.sleep(0)  # let the task start
    await logic.ensure_stopped()


async def _set_and_wait(cancelling: asyncio.Event, monkeypatch: pytest.MonkeyPatch):
    async def wait_for_value(self, signal, timeout):
        await _slow_to_cancel(cancelling)

    monkeypatch.setattr(signal_module._ValueChecker, "wait_for_value", wait_for_value)
    sig = soft_signal_rw(int)
    await sig.connect()
    # No initial value ever arrives, so this times out and the error handler
    # cancels the slow to cancel wait task
    with pytest.raises(TimeoutError):
        await signal_module.set_and_wait_for_value(sig, 1, timeout=0.1)


@pytest.mark.parametrize(
    "cleanup", [_status_aexit, _blob_ensure_stopped, _set_and_wait]
)
async def test_cancelling_caller_during_cleanup_waits_for_it_then_raises(
    cleanup: Callable[[asyncio.Event, pytest.MonkeyPatch], Coroutine[Any, Any, None]],
    monkeypatch: pytest.MonkeyPatch,
):
    cancelling = asyncio.Event()
    outer = asyncio.create_task(cleanup(cancelling, monkeypatch))
    # Cancel the caller while the cleanup is waiting for the inner task to finish
    await cancelling.wait()
    outer.cancel()
    await asyncio.wait([outer])
    assert outer.cancelled()
    # The caller ended only once the slow cleanup had finished
    assert asyncio.all_tasks() == {asyncio.current_task()}
