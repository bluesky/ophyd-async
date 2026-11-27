import asyncio
from collections.abc import Callable, Coroutine
from typing import Any
from unittest.mock import Mock

import pytest

from ophyd_async.core import AsyncStatus, callback_on_mock_put, soft_signal_rw

# The waits these cleanups cancel are internal, with no public way to slow them down
from ophyd_async.core import _signal as signal_module  # noqa: PLC2701
from ophyd_async.sim._blob_acquire_logic import BlobAcquireLogic  # noqa: PLC2701
from ophyd_async.testing import wait_for_pending_wakeups


class SlowToCancel:
    """Coroutines that finish cancelling only once `release` is set, like slow async
    cleanup."""

    def __init__(self):
        self.cancelling = asyncio.Event()
        self.release = asyncio.Event()

    def coro(self):
        async def coro():
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.cancelling.set()
                await self.release.wait()
                raise

        return coro()


async def _status_aexit(slow: SlowToCancel, _: pytest.MonkeyPatch):
    async with AsyncStatus(slow.coro()):
        await wait_for_pending_wakeups()  # let the status task start


async def _blob_ensure_stopped(slow: SlowToCancel, _: pytest.MonkeyPatch):
    pattern_generator = Mock()
    pattern_generator.write_images_to_file = slow.coro
    logic = BlobAcquireLogic(pattern_generator)
    await logic.start_acquiring()
    await wait_for_pending_wakeups()  # let the task start
    await logic.ensure_stopped()


async def _set_and_wait(slow: SlowToCancel, monkeypatch: pytest.MonkeyPatch):
    async def wait_for_value(self, signal, timeout):
        self.got_first_value.set()
        await slow.coro()

    def fail_put(value):
        raise ValueError("put failed")

    monkeypatch.setattr(signal_module._ValueChecker, "wait_for_value", wait_for_value)
    sig = soft_signal_rw(int)
    await sig.connect(mock=True)
    callback_on_mock_put(sig, fail_put)
    # The set fails, so the error handler cancels the slow to cancel wait task
    with pytest.raises(ValueError):
        await signal_module.set_and_wait_for_value(sig, 1)


@pytest.mark.parametrize(
    "cleanup", [_status_aexit, _blob_ensure_stopped, _set_and_wait]
)
async def test_cancelling_caller_during_cleanup_waits_for_it_then_raises(
    cleanup: Callable[[SlowToCancel, pytest.MonkeyPatch], Coroutine[Any, Any, None]],
    monkeypatch: pytest.MonkeyPatch,
):
    slow = SlowToCancel()
    outer = asyncio.create_task(cleanup(slow, monkeypatch))
    # Cancel the caller while the cleanup is waiting for the inner task to finish
    await slow.cancelling.wait()
    outer.cancel()
    await wait_for_pending_wakeups()
    assert not outer.done()
    slow.release.set()
    await asyncio.wait([outer])
    assert outer.cancelled()
    # The caller ended only once the slow cleanup had finished
    assert asyncio.all_tasks() == {asyncio.current_task()}
