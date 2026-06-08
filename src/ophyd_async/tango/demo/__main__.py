"""Used for tutorial `Implementing Devices`."""

# Import bluesky and ophyd
import bluesky.plan_stubs as bps  # noqa: F401
import bluesky.plans as bp  # noqa: F401
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.run_engine import RunEngine, autoawait_in_bluesky_event_loop

from ophyd_async.core import init_devices
from ophyd_async.tango import demo
from ophyd_async.tango.testing import generate_random_trl_prefix

# Create a run engine and make ipython use it for `await` commands
RE = RunEngine(call_returns_result=True)
autoawait_in_bluesky_event_loop()

# Add a callback for plotting
bec = BestEffortCallback()
RE.subscribe(bec)

# Start demo DeviceServer in subprocess
prefix = generate_random_trl_prefix()
ds = demo.start_device_server_subprocess(prefix, num_channels=3)

# All Devices created within this block will be
# connected and named at the end of the with block
with init_devices():
    # Create a sample stage with X and Y motors
    stage = demo.DemoStage(ds.trls[f"{prefix}/X"], ds.trls[f"{prefix}/Y"])
    # Create a multi channel counter with the same number
    # of counters as the IOC
    pdet = demo.DemoPointDetector(
        ds.trls[f"{prefix}/DET"],
        [
            ds.trls[f"{prefix}/C1"],
            ds.trls[f"{prefix}/C2"],
            ds.trls[f"{prefix}/C3"],
        ],
    )
