# need to be able to test that I can initialise a detector, run a plan on it,
# and it writes to the directory given to it.


from typing import AsyncIterator, Dict, Union, cast
import pytest

from ophyd_async.core import StandardDetector, DeviceCollector, StaticDirectoryProvider
from bluesky.protocols import Descriptor
from event_model import StreamDatum, StreamResource
from ophyd_async.core.signal import set_sim_value

from ophyd_async.epics.areadetector.controllers import StandardController
from ophyd_async.epics.areadetector.drivers import ADDriver, ADDriverShapeProvider
from ophyd_async.epics.areadetector.writers import HDFWriter, NDFileHDF
from pathlib import Path

import bluesky.plans as bp
import bluesky.plan_stubs as bps
from bluesky import RunEngine
import time


CURRENT_DIRECTORY = Path(__file__).parent

@pytest.fixture
async def detector(RE: RunEngine) -> StandardDetector:
    async with DeviceCollector(sim=True):
        driver = ADDriver("test-driver:")
        hdf = NDFileHDF("test-hdf:")
    
        controller = StandardController(driver)
        writer = HDFWriter(hdf, StaticDirectoryProvider(CURRENT_DIRECTORY, "temporary_file"), lambda: "test", ADDriverShapeProvider(driver))

        detector = StandardDetector(controller, writer, [driver.acquire_time])

    set_sim_value(driver.array_size_x, 10)
    set_sim_value(driver.array_size_y, 20)
    return detector

async def test_detector_writes_to_file(RE: RunEngine, detector: StandardDetector):
    names = []
    docs = []
    RE.subscribe(lambda name, _: names.append(name))
    RE.subscribe(lambda _, doc: docs.append(doc))
    RE(bp.count([detector], 3))
    

    assert await cast(HDFWriter, detector.data).hdf.file_path.get_value() == CURRENT_DIRECTORY
    
    descriptor_index = names.index("descriptor")

    assert docs[descriptor_index].get("data_keys").get("test").get("shape") == (20, 10)
    #assert names == ['start', 'descriptor', 'stream_resource', 'stream_datum', 'event', 'stream_datum', 'event', 'stream_datum', 'event', 'stop']

async def test_read_and_describe_detector(detector: StandardDetector):
    describe = await detector.describe_configuration()
    read = await detector.read_configuration()

    assert describe == {
        "driver-acquire_time": {"source": "sim://test-driver:AcquireTime_RBV", "dtype": "number", "shape": []}
    }
    assert read == {'driver-acquire_time': {'value': 0.0, 'timestamp': pytest.approx(time.monotonic()), 'alarm_severity': 0}}

async def test_read_returns_nothing(detector: StandardDetector):
    assert await detector.read() == {}

