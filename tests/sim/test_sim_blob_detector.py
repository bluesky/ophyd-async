import os
from collections import defaultdict

import bluesky.plan_stubs as bps
import bluesky.plans as bp
import bluesky.preprocessors as bpp
import h5py
import numpy as np
import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import StaticFilenameProvider, StaticPathProvider, TriggerInfo
from ophyd_async.sim import SimBlobDetector
from ophyd_async.testing import assert_emitted


@pytest.fixture
def blob_detector(tmp_path) -> SimBlobDetector:
    path_provider = StaticPathProvider(StaticFilenameProvider("file"), tmp_path)
    return SimBlobDetector(path_provider, name="det")


@pytest.mark.parametrize("x_position,det_sum", [(0.0, 277544), (1.0, 506344)])
async def test_sim_blob_detector_count(
    RE: RunEngine,
    tmp_path,
    x_position: float,
    det_sum: int,
    blob_detector: SimBlobDetector,
):
    docs = defaultdict(list)
    RE.subscribe(lambda name, doc: docs[name].append(doc))
    blob_detector.pattern_generator.set_x(x_position)

    RE(bp.count([blob_detector], num=2))
    assert_emitted(
        docs, start=1, descriptor=1, stream_resource=2, stream_datum=4, event=2, stop=1
    )
    path = docs["stream_resource"][0]["uri"].split("://localhost")[-1]
    if os.name == "nt":
        path = path.lstrip("/")
    # Check data looks right
    assert path == str(tmp_path / "file.h5")
    h5file = h5py.File(path)
    assert list(h5file["/entry"]) == ["data", "sum"]
    assert list(h5file["/entry/sum"]) == [det_sum, det_sum]
    assert np.sum(h5file["/entry/data/data"][0]) == det_sum
    # Check descriptor looks right
    assert docs["descriptor"][0]["data_keys"] == {
        "det": {
            "source": "sim://pattern-generator-hdf-file",
            "shape": [240, 320],
            "dtype": "array",
            "object_name": "det",
            "external": "STREAM:",
        },
        "det-sum": {
            "source": "sim://pattern-generator-hdf-file",
            "shape": [],
            "dtype": "number",
            "object_name": "det",
            "external": "STREAM:",
        },
    }


async def test_sim_blob_detector_fly(
    RE: RunEngine,
    tmp_path,
    blob_detector: SimBlobDetector,
):
    @bpp.stage_decorator([blob_detector])
    @bpp.run_decorator()
    def fly_plan():
        yield from bps.prepare(
            blob_detector, TriggerInfo(number_of_triggers=7), wait=True
        )
        yield from bps.declare_stream(blob_detector, name="primary")
        yield from bps.kickoff(blob_detector, wait=True)
        yield from bps.collect_while_completing(
            flyers=[blob_detector], dets=[blob_detector], flush_period=0.5
        )

    docs = defaultdict(list)
    RE.subscribe(lambda name, doc: docs[name].append(doc))

    RE(fly_plan())
    assert_emitted(
        docs, start=1, descriptor=1, stream_resource=2, stream_datum=4, stop=1
    )
    # Check we get the right numbers of frames in each stream_datum
    assert (
        docs["stream_datum"][0]["indices"]
        == docs["stream_datum"][1]["indices"]
        == {
            "start": 0,
            "stop": 4,
        }
    )
    assert (
        docs["stream_datum"][2]["indices"]
        == docs["stream_datum"][3]["indices"]
        == {
            "start": 4,
            "stop": 7,
        }
    )
