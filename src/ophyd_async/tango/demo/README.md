The following is intended to be a demonstration of Tango support for ophyd-async.
The usage of the Tango control system without a real Tango server is limited and
intended to be used in tests. All operations using the demo devices must be performed
within the MultiDeviceTestContext context as demonstrated here.

```python
from tango.test_context import MultiDeviceTestContext
from ophyd_async.tango.demo import (
    DemoMover,
    TangoMover,
    DemoCounter,
    TangoCounter,
)

from bluesky import RunEngine
import bluesky.plans as bp
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.utils import ProgressBarManager

content = (
    {
        "class": DemoMover,
        "devices": [
            {"name": "demo/motor/1"}
        ],
    },
    {
        "class": DemoCounter,
        "devices": [
            {"name": "demo/counter/1"},
            {"name": "demo/counter/2"}
        ],
    }
)
tango_context = MultiDeviceTestContext(content)
with tango_context as context:    
    motor1 = TangoMover(trl=context.get_device_access("demo/motor/1"), name="motor1")
    counter1 = TangoCounter(trl=context.get_device_access("demo/counter/1"), name="counter1")
    counter2 = TangoCounter(trl=context.get_device_access("demo/counter/2"), name="counter2")
    await motor1.connect()
    await counter1.connect()
    await counter2.connect()
    
    # Events are not supported by the test context so we disable them
    motor1.position._backend.allow_events(False)
    motor1.state._backend.allow_events(False)
    # Enable polling for the position and state attributes
    motor1.position._backend.set_polling(True, 0.1, 0.1)
    motor1.state._backend.set_polling(True, 0.1)
    
    RE = RunEngine()
    RE.subscribe(BestEffortCallback())
    RE.waiting_hook = ProgressBarManager()
    #RE(bps.mv(motor1, 1))
    RE(bp.scan([counter1, counter2], motor1, -1, 1, 10))
```