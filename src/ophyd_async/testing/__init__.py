import asyncio


async def wait_for_pending_wakeups(max_yields=20, raise_if_exceeded=True):
    """Allow any ready asyncio tasks to be woken up.

    Used in:

    - Tests to allow tasks like ``set()`` to start so that signal
      puts can be tested
    - `observe_value` to allow it to be wrapped in `asyncio.wait_for`
      with a timeout
    """
    loop = asyncio.get_event_loop()
    # If anything has called loop.call_soon or is scheduled a wakeup
    # then let it run
    for _ in range(max_yields):
        await asyncio.sleep(0)
        if not loop._ready:  # type: ignore # noqa: SLF001
            return
    if raise_if_exceeded:
        raise RuntimeError(f"Tasks still scheduling wakeups after {max_yields} yields")
