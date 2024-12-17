# Import bluesky and ophyd
import bluesky.plan_stubs as bps  # noqa: F401
import bluesky.plans as bp  # noqa: F401
from bluesky.run_engine import RunEngine, autoawait_in_bluesky_event_loop

from ophyd_async.core import StaticPathProvider, UUIDFilenameProvider, init_devices
from ophyd_async.sim import demo

# Create a run engine and make ipython use it for `await` commands
RE = RunEngine(call_returns_result=True)
autoawait_in_bluesky_event_loop()

# Define where test data should be written
path_provider = StaticPathProvider(UUIDFilenameProvider(), "/tmp")

# All Devices created within this block will be
# connected and named at the end of the with block
with init_devices():
    # Create a couple of simulated motors
    x = demo.SimMotor()
    y = demo.SimMotor()
    # Make a pattern generator that uses the motor positions
    # to make a test pattern. This simulates the real life process
    # of X-ray scattering off a sample
    generator = demo.PatternGenerator(
        x_signal=x.user_readback,
        y_signal=y.user_readback,
    )
    # Make a detector device that wraps the generator
    det = demo.PatternDetector(path_provider, generator)
