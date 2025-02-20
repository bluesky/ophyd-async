from collections.abc import Awaitable

import bluesky.plan_stubs as bps
from bluesky.utils import MsgGenerator, plan

from ._utils import T


@plan
def wait_for_awaitable(coro: Awaitable[T]) -> MsgGenerator[T]:
    """Wait for a single awaitable to complete, and return the result."""
    (task,) = yield from bps.wait_for([lambda: coro])
    return task.result()
