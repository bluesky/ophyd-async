from bluesky.run_engine import RunEngine

from ophyd_async.core import DeviceCollector

from ._eiger_io import EigerDriverIO

RE = RunEngine()

with DeviceCollector():
    driver = EigerDriverIO("EIGER-455:")
