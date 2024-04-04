import asyncio

import pytest

from ophyd_async.core.async_status import AsyncStatus
from ophyd_async.core.signal import SignalR, SimSignalBackend
from ophyd_async.core.standard_readable import StandardReadable


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


async def test_asyncstatus_wraps_set():
    class TestDevice(StandardReadable):
        def __init__(self, name: str = "") -> None:
            self.sig = SignalR(
                backend=SimSignalBackend(datatype=int, source="sim:TEST")
            )
            super().__init__(name)

        @AsyncStatus.wrap
        async def set(self, val):
            await asyncio.sleep(0.01)
            self.sig._backend._set_value(val)  # type: ignore

    TD = TestDevice()
    await TD.connect()
    st = TD.set(5)
    assert isinstance(st, AsyncStatus)
    await st
    assert (await TD.sig.get_value()) == 5
