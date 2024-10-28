import asyncio
import traceback
from unittest.mock import Mock

import bluesky.plan_stubs as bps
import pytest
from bluesky.protocols import Movable, Status
from bluesky.utils import FailedStatus

from ophyd_async.core import AsyncStatus, Device, completed_status


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
    status = AsyncStatus(normal_coroutine())
    assert status.exception() is None

    status.task.exception = Mock(side_effect=asyncio.CancelledError(""))
    await status

    assert isinstance(status.exception(), asyncio.CancelledError)


async def test_async_status_has_no_exception_if_coroutine_successful(normal_coroutine):
    status = AsyncStatus(normal_coroutine())
    assert status.exception() is None

    await status

    assert status.exception() is None


async def test_async_status_success_if_cancelled(normal_coroutine):
    cbs = []
    coro = normal_coroutine()
    status = AsyncStatus(coro)
    status.add_callback(cbs.append)
    assert status.exception() is None
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
    normal_task = asyncio.Task(normal_coroutine())
    status = AsyncStatus(normal_task)

    await status
    assert status.success is True


async def test_async_status_str_for_normal_coroutine(normal_coroutine):
    normal_task = asyncio.Task(normal_coroutine())
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


class FailingMovable(Movable, Device):
    def _fail(self):
        raise ValueError("This doesn't work")

    async def _set(self, value):
        if value:
            self._fail()

    def set(self, value) -> AsyncStatus:
        return AsyncStatus(self._set(value))


async def test_status_propogates_traceback_under_RE(RE) -> None:
    expected_call_stack = ["_set", "_fail"]
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
