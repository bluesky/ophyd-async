from collections import defaultdict

import bluesky.plans as bp
import h5py
import numpy as np
from bluesky import RunEngine

from ophyd_async.core import assert_emitted
from ophyd_async.plan_stubs import ensure_connected
from ophyd_async.sim.demo import PatternDetector


async def test_sim_pattern_detector_initialization(
    sim_pattern_detector: PatternDetector,
):
    assert (
        sim_pattern_detector.pattern_generator
    ), "PatternGenerator was not initialized correctly."


async def test_detector_creates_controller_and_writer(
    sim_pattern_detector: PatternDetector,
):
    assert sim_pattern_detector.writer
    assert sim_pattern_detector.controller


def test_writes_pattern_to_file(
    sim_pattern_detector: PatternDetector,
    RE: RunEngine,
):
    # assert that the file contains data in expected dimensions
    docs = defaultdict(list)

    def capture_emitted(name, doc):
        docs[name].append(doc)

    def plan():
        yield from ensure_connected(sim_pattern_detector, mock=True)
        yield from bp.count([sim_pattern_detector])

    RE(plan(), capture_emitted)
    assert_emitted(
        docs, start=1, descriptor=1, stream_resource=2, stream_datum=2, event=1, stop=1
    )
    path = docs["stream_resource"][0]["uri"].split("://localhost")[-1]
    h5file = h5py.File(path)
    assert list(h5file["/entry"]) == ["data", "sum"]
    assert list(h5file["/entry/sum"]) == [44540.0]
    assert np.sum(h5file["/entry/data/data"]) == 44540.0
