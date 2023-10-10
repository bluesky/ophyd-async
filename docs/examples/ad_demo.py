import bluesky.plan_stubs as bps
import bluesky.plans as bp  # noqa
import bluesky.preprocessors as bpp

# Import bluesky and ophyd
import matplotlib.pyplot as plt
from bluesky import RunEngine
from bluesky.callbacks.best_effort import BestEffortCallback
from bluesky.utils import ProgressBarManager, register_transform

from ophyd_async.epics import areadetector
from ophyd_async.core import DeviceCollector
# Create a run engine, with plotting, progressbar and transform
RE = RunEngine({}, call_returns_result=True)
bec = BestEffortCallback()
RE.subscribe(bec)
RE.waiting_hook = ProgressBarManager()
plt.ion()
register_transform("RE", prefix="<")

# Start IOC with demo pvs in subprocess
pv_prefix = "pc0105-AD-SIM-01:"


# Create v2 devices
with DeviceCollector():
    det3 = areadetector.Pilatus(pv_prefix)


# And a plan
@bpp.run_decorator()
@bpp.stage_decorator([det3])
def fly_det3(num: int):
    yield from bps.mov(det3.drv.num_images, num)
    yield from bps.kickoff(det3, wait=True)
    status = yield from bps.complete(det3, wait=False, group="complete")
    while status and not status.done:
        yield from bps.collect(det3, stream=True, return_payload=False)
        yield from bps.sleep(0.1)
    yield from bps.wait(group="complete")
    # One last one
    yield from bps.collect(det3, stream=True, return_payload=False)
