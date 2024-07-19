from bluesky import RunEngine
from ophyd_async.epics import demo
from bluesky.plans import count
re = RunEngine()
pv_prefix = demo.start_ioc_subprocess()
det = demo.Sensor(pv_prefix, name="det")
await det.connect()
re(count([det]))
