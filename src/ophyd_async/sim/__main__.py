"""Used for tutorial `Using Devices`."""

# Import bluesky and ophyd
from pathlib import PurePath
from tempfile import mkdtemp

import bluesky.plan_stubs as bps  # noqa: F401
import bluesky.plans as bp  # noqa: F401
import bluesky.preprocessors as bpp  # noqa: F401
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.run_engine import RunEngine, autoawait_in_bluesky_event_loop

from ophyd_async import sim
from ophyd_async.core import StaticPathProvider, UUIDFilenameProvider, init_devices

# Create a run engine and make ipython use it for `await` commands
RE = RunEngine(call_returns_result=True)
autoawait_in_bluesky_event_loop()

# Add a callback for plotting
bec = BestEffortCallback()
RE.subscribe(bec)

# Make a pattern generator that uses the motor positions
# to make a test pattern. This simulates the real life process
# of X-ray scattering off a sample
pattern_generator = sim.PatternGenerator()

# Make a path provider that makes UUID filenames within a static
# temporary directory
path_provider = StaticPathProvider(UUIDFilenameProvider(), PurePath(mkdtemp()))

# All Devices created within this block will be
# connected and named at the end of the with block
with init_devices():
    # Create a sample stage with X and Y motors that report their positions
    # to the pattern generator
    stage = sim.SimStage(pattern_generator)
    # Make a detector device that gives the point value of the pattern generator
    # when triggered
    pdet = sim.SimPointDetector(pattern_generator)
    # Make a detector device that gives a gaussian blob with intensity based
    # on the point value of the pattern generator when triggered
    bdet = sim.SimBlobDetector(path_provider, pattern_generator)
