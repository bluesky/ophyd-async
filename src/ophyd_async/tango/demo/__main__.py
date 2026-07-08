"""Used for tutorial `Implementing Devices`."""

import atexit

# Import bluesky and ophyd
import bluesky.plan_stubs as bps  # noqa: F401
import bluesky.plans as bp  # noqa: F401
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.run_engine import RunEngine, autoawait_in_bluesky_event_loop

from ophyd_async.core import init_devices
from ophyd_async.tango import demo, testing

# Create a run engine and make ipython use it for `await` commands
RE = RunEngine(call_returns_result=True)
autoawait_in_bluesky_event_loop()

# Add a callback for plotting
bec = BestEffortCallback()
RE.subscribe(bec)

# Start demo device servers in subprocess
prefix = testing.generate_random_trl_prefix()
servers = testing.start_tango_device_servers("demo", prefix)
atexit.register(servers.stop)


def trl(device_name: str) -> str:
    """Predict the TRL of `device_name`, served by `servers` under `prefix`."""
    return demo.predict_trl(prefix, device_name)


# All Devices created within this block will be
# connected and named at the end of the with block
with init_devices():
    # Create a sample stage with X and Y motors
    stage = demo.DemoStage(trl("motor-x"), trl("motor-y"))
    # Create a multi channel counter with the same number
    # of counters as the device servers
    pdet = demo.DemoPointDetector(
        trl("detector"),
        [trl("channel-1"), trl("channel-2"), trl("channel-3")],
    )
