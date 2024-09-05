import asyncio

import bluesky.plans as bp
from bluesky import RunEngine
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.utils import ProgressBarManager

from ophyd_async.tango.demo import (
    DemoCounter,
    DemoMover,
    TangoCounter,
    TangoMover,
)
from tango.test_context import MultiDeviceTestContext

content = (
    {
        "class": DemoMover,
        "devices": [{"name": "demo/motor/1"}],
    },
    {
        "class": DemoCounter,
        "devices": [{"name": "demo/counter/1"}, {"name": "demo/counter/2"}],
    },
)

tango_context = MultiDeviceTestContext(content)


async def main():
    with tango_context as context:
        motor1 = TangoMover(
            trl=context.get_device_access("demo/motor/1"), name="motor1"
        )
        counter1 = TangoCounter(
            trl=context.get_device_access("demo/counter/1"), name="counter1"
        )
        counter2 = TangoCounter(
            trl=context.get_device_access("demo/counter/2"), name="counter2"
        )
        await motor1.connect()
        await counter1.connect()
        await counter2.connect()

        RE = RunEngine()
        RE.subscribe(BestEffortCallback())
        RE.waiting_hook = ProgressBarManager()
        # RE(bps.mv(motor1, 1))
        RE(bp.scan([counter1, counter2], motor1, -1, 1, 10))


if __name__ == "__main__":
    asyncio.run(main())
