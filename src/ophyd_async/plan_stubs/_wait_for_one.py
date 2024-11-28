from collections.abc import Awaitable

import bluesky.plan_stubs as bps
from bluesky.utils import MsgGenerator, plan

from ophyd_async.core import T


@plan
def wait_for_one(coro: Awaitable[T]) -> MsgGenerator[T]:
    (task,) = yield from bps.wait_for([lambda: coro])
    return task.result()
