"""Used for tutorial `Implementing Devices`."""

# Import bluesky and ophyd
import bluesky.plan_stubs as bps  # noqa: F401
import bluesky.plans as bp  # noqa: F401
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.run_engine import RunEngine, autoawait_in_bluesky_event_loop

from ophyd_async.core import init_devices
from ophyd_async.tango import demo

from ._tango import start_device_server_subprocess

# Create a run engine and make ipython use it for `await` commands
RE = RunEngine(call_returns_result=True)
autoawait_in_bluesky_event_loop()

# Add a callback for plotting
bec = BestEffortCallback()
RE.subscribe(bec)

# Start demo DeviceServer in subprocess
prefix = "test/device"
ds = start_device_server_subprocess(prefix, num_channels=3)

# All Devices created within this block will be
# connected and named at the end of the with block
with init_devices():
    # Create a sample stage with X and Y motors
    stage = demo.DemoStage(ds.trls["test/device/X"], ds.trls["test/device/Y"])
    # Create a multi channel counter with the same number
    # of counters as the IOC
    pdet = demo.DemoPointDetector(
        ds.trls["test/device/DET"],
        [
            ds.trls["test/device/C1"],
            ds.trls["test/device/C2"],
            ds.trls["test/device/C3"],
        ],
    )
