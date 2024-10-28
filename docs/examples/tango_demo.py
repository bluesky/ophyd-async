import asyncio

import bluesky.plan_stubs as bps
import bluesky.plans as bp
from bluesky import RunEngine

from ophyd_async.tango.demo import (
    DemoCounter,
    DemoMover,
    TangoDetector,
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
    with tango_context:
        detector = TangoDetector(
            trl="",
            name="detector",
            counters_kwargs={"prefix": "demo/counter/", "count": 2},
            mover_kwargs={"trl": "demo/motor/1"},
        )
        await detector.connect()

        RE = RunEngine()

        RE(bps.read(detector))
        RE(bps.mv(detector, 0))
        RE(bp.count(list(detector.counters.values())))

        set_status = detector.set(1.0)
        await asyncio.sleep(0.1)
        stop_status = detector.stop()
        await set_status
        await stop_status
        assert all([set_status.done, stop_status.done])
        assert all([set_status.success, stop_status.success])


if __name__ == "__main__":
    asyncio.run(main())
