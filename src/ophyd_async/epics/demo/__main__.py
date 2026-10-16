"""Used for tutorial `Implementing Devices`."""

import atexit

# Import bluesky and ophyd
import bluesky.plan_stubs as bps  # noqa: F401
import bluesky.plans as bp  # noqa: F401
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.run_engine import RunEngine, autoawait_in_bluesky_event_loop

from ophyd_async.core import init_devices
from ophyd_async.epics import demo, testing

# Create a run engine and make ipython use it for `await` commands
RE = RunEngine(call_returns_result=True)
autoawait_in_bluesky_event_loop()

# Add a callback for plotting
bec = BestEffortCallback()
RE.subscribe(bec)

# Start IOC with demo pvs in subprocess
NUM_CHANNELS = 3
prefix = testing.generate_random_pv_prefix()
ioc = testing.start_ioc(demo.IOC, prefix, str(NUM_CHANNELS))
atexit.register(ioc.stop)

# All Devices created within this block will be
# connected and named at the end of the with block
with init_devices():
    # Create a sample stage with X and Y motors
    stage = demo.DemoStage(f"{prefix}STAGE:")
    # Create a multi channel counter with the same number
    # of counters as the IOC
    pdet = demo.DemoPointDetector(f"{prefix}DET:", num_channels=NUM_CHANNELS)
