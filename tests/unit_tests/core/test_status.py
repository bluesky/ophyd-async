import asyncio
import contextlib
import re
import time
import traceback
from asyncio import CancelledError
from unittest.mock import Mock

import bluesky.plan_stubs as bps
import pytest
from bluesky.protocols import Movable, Status
from bluesky.utils import FailedStatus

from ophyd_async.core import AsyncStatus, Device, completed_status


@contextlib.contextmanager
def timing_check(expected_time: float, abs_tolerance: float = 0.1):
    """Context manager to assert execution time is approximately as expected."""
    start = time.monotonic()
    yield
    end = time.monotonic()
    assert end - start == pytest.approx(expected_time, abs=abs_tolerance)


async def test_async_status_success():
    st = AsyncStatus(asyncio.sleep(0.1))
    assert isinstance(st, Status)
    assert not st.done
    assert not st.success
    await st
    assert st.done
    assert st.success


async def test_async_status_propagates_exception(failing_coroutine):
    status = AsyncStatus(failing_coroutine())
    assert status.exception() is None

    with pytest.raises(ValueError):
        await status

    assert isinstance(status.exception(), ValueError)


async def test_async_status_propagates_cancelled_error(normal_coroutine):
    coro, is_running = normal_coroutine
    status = AsyncStatus(coro())
    assert status.exception() is None

    status.task.exception = Mock(side_effect=asyncio.CancelledError(""))
    await status

    assert isinstance(status.exception(), asyncio.CancelledError)


class SelfCancellingDevice(Device):
    @AsyncStatus.wrap
    async def set(self, value):
        await asyncio.sleep(0.1)
        raise CancelledError()


async def test_async_status_propagates_cancelled_error_with_message():
    device = SelfCancellingDevice("MY_DEVICE")

    with pytest.raises(CancelledError) as e:
        await device.set(1)

    assert re.search("CancelledError while awaiting .*MY_DEVICE", e.value.args[0])


async def test_async_status_has_no_exception_if_coroutine_successful(normal_coroutine):
    coro, is_running = normal_coroutine
    status = AsyncStatus(coro())
    assert status.exception() is None

    await status

    assert status.exception() is None


@pytest.mark.parametrize("wait_to_run", [True, False])
async def test_async_status_success_if_cancelled(normal_coroutine, wait_to_run):
    cbs = []
    coro, is_running = normal_coroutine
    status = AsyncStatus(coro())
    status.add_callback(cbs.append)
    assert status.exception() is None
    if wait_to_run:
        await is_running.wait()
    status.task.cancel()
    assert not cbs
    with pytest.raises(asyncio.CancelledError):
        await status
    assert cbs == [status]
    assert status.success is False
    assert isinstance(status.exception(), asyncio.CancelledError)


async def coroutine_to_wrap(time: float):
    await asyncio.sleep(time)


async def test_async_status_wrap() -> None:
    wrapped_coroutine = AsyncStatus.wrap(coroutine_to_wrap)
    status: AsyncStatus = wrapped_coroutine(0.01)

    await status
    assert status.success is True


async def test_async_status_initialised_with_a_task(normal_coroutine):
    coro, is_running = normal_coroutine
    normal_task = asyncio.Task(coro())
    status = AsyncStatus(normal_task)

    await status
    assert status.success is True


async def test_async_status_str_for_normal_coroutine(normal_coroutine):
    coro, is_running = normal_coroutine
    normal_task = asyncio.Task(coro())
    status = AsyncStatus(normal_task)

    for comment_chunk in ["<AsyncStatus,", "normal_coroutine", "pending>"]:
        assert comment_chunk in str(status)
    await status

    for comment_chunk in ["<AsyncStatus,", "normal_coroutine", "done>"]:
        assert comment_chunk in str(status)


async def test_async_status_str_for_failing_coroutine(failing_coroutine):
    failing_task = asyncio.Task(failing_coroutine())
    status = AsyncStatus(failing_task)

    for comment_chunk in ["<AsyncStatus,", "failing_coroutine", "pending>"]:
        assert comment_chunk in str(status)
    with pytest.raises(ValueError):
        await status

    for comment_chunk in [
        "<AsyncStatus,",
        "failing_coroutine",
        "errored:",
        "ValueError",
    ]:
        assert comment_chunk in str(status)


async def test_status_complete_loop_continues():
    vals = []
    # When the status completes, the loop body must NOT be interrupted;
    # the context manager only cancels the status task on exit, not the caller.
    async with AsyncStatus(asyncio.sleep(0.01)):
        for i in range(5):
            vals.append(i)
            await asyncio.sleep(0.02)  # status finishes during first sleep
    assert vals == [0, 1, 2, 3, 4]


async def test_context_manager_does_not_cancel_caller():
    # Guard against regressions: wrapping a loop in `async with status:` without
    # done_status should NOT cause the loop to exit when the status finishes.
    vals = []
    status = AsyncStatus(asyncio.sleep(0))
    await asyncio.sleep(0.01)  # Ensure status is already done
    assert status.done

    async with status:
        for i in range(5):
            vals.append(i)
            await asyncio.sleep(0)
    assert vals == [0, 1, 2, 3, 4]


async def test_loop_complete_before_status_complete():
    vals = []

    # If the loop completes before the status, then it
    # should cancel the task the status is waiting for
    async def deferred_put():
        await asyncio.sleep(1)
        vals.append("deferred_put")

    with timing_check(0.02):
        async with AsyncStatus(deferred_put()):
            for i in range(2):
                vals.append(i)
                await asyncio.sleep(0.01)
    assert vals == [0, 1]
    # Check that if we wait a while it still didn't put deferred_put onto the list
    await asyncio.sleep(0.01)
    assert vals == [0, 1]


async def test_error_raised_from_with_status():
    vals = []
    # If an error is raised from the loop then it should be raised
    with timing_check(0):
        with pytest.raises(ValueError, match="breaking out"):
            async with AsyncStatus(asyncio.sleep(1)):
                for i in range(2):
                    vals.append(i)
                    raise ValueError("breaking out")
    assert vals == [0]


async def test_status_coroutine_raises_exception(failing_coroutine):
    vals = []
    # The exception from the status task should propagate out
    with timing_check(0.1):
        with pytest.raises(ValueError):
            async with AsyncStatus(failing_coroutine()):
                for i in range(10):
                    vals.append(i)
                    await asyncio.sleep(0.01)
    # Loop should complete and error only be raised at the end
    assert vals == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]


async def test_awaiting_status_inside_its_own_context():
    vals = []

    async with AsyncStatus(asyncio.sleep(0.01)) as status:
        vals.append(0)
        await status  # Explicitly await the status
        vals.append(1)

    assert vals == [0, 1]


async def test_no_await_points_in_loop_body():
    vals = []

    with timing_check(0.01):
        async with AsyncStatus(asyncio.sleep(0)):
            for i in range(100):
                vals.append(i)
                # No await here - tight loop
    # Without await points, the loop should complete many iterations
    # before the event loop can process the cancellation
    assert len(vals) == 100


async def test_both_status_and_loop_raise_exceptions():
    vals = []

    async def failing_status():
        await asyncio.sleep(0.05)
        raise RuntimeError("Status failed")

    # Loop raises first, so its exception should propagate
    with pytest.raises(ValueError, match="Loop failed"):
        async with AsyncStatus(failing_status()):
            vals.append(0)
            await asyncio.sleep(0.01)
            raise ValueError("Loop failed")

    assert vals == [0]


class FailingMovable(Movable, Device):
    def _fail(self):
        raise ValueError("This doesn't work")

    @AsyncStatus.wrap
    async def set(self, value):
        if value:
            return self._fail()


async def test_status_propogates_traceback_under_re(RE) -> None:
    expected_call_stack = ["wait_with_error_message", "set", "_fail"]
    d = FailingMovable()
    with pytest.raises(FailedStatus) as ctx:
        RE(bps.mv(d, 3))
    # We get "The above exception was the direct cause of the following exception:",
    # so extract that first exception traceback and check
    assert ctx.value.__cause__
    assert expected_call_stack == [
        x.name for x in traceback.extract_tb(ctx.value.__cause__.__traceback__)
    ]
    # Check we get the same from the status.exception
    status: AsyncStatus = ctx.value.args[0]
    exception = status.exception()
    assert exception
    assert expected_call_stack == [
        x.name for x in traceback.extract_tb(exception.__traceback__)
    ]


async def test_async_status_exception_timeout():
    st = AsyncStatus(asyncio.sleep(0.1))
    try:
        with pytest.raises(
            ValueError,
            match=(
                "cannot honour any timeout other than 0 in an asynchronous function"
            ),
        ):
            st.exception(timeout=1.0)
    finally:
        if not st.done:
            st.task.cancel()


@pytest.fixture
def loop():
    return asyncio.get_event_loop()


def test_asyncstatus_wraps_bare_func(loop):
    async def do_test():
        @AsyncStatus.wrap
        async def coro_status():
            await asyncio.sleep(0.01)

        st = coro_status()
        assert isinstance(st, AsyncStatus)
        await asyncio.wait_for(st.task, None)
        assert st.done

    loop.run_until_complete(do_test())


def test_asyncstatus_wraps_bare_func_with_args_kwargs(loop):
    async def do_test():
        test_result = 5

        @AsyncStatus.wrap
        async def coro_status(x: int, y: int, *, z=False):
            await asyncio.sleep(0.01)
            nonlocal test_result
            test_result = x * y if z else 0

        st = coro_status(3, 4, z=True)
        assert isinstance(st, AsyncStatus)
        await asyncio.wait_for(st.task, None)
        assert st.done
        assert test_result == 12

    loop.run_until_complete(do_test())


async def test_completed_status():
    with pytest.raises(ValueError):
        await completed_status(ValueError())
    await completed_status()


async def test_device_name_in_failure_message_asyncstatus_wrap(RE):
    device_name = "MyFailingMovable"
    d = FailingMovable(name=device_name)
    with pytest.raises(FailedStatus) as ctx:
        RE(bps.mv(d, 3))
    # FailingMovable.set is decorated with @AsyncStatus.wrap
    # undecorated methods will not print the device name
    status: AsyncStatus = ctx.value.args[0]
    assert f"device: {device_name}" in repr(status)
