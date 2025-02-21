import os
from collections import defaultdict

import bluesky.plans as bp
import h5py
import numpy as np
import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import StaticFilenameProvider, StaticPathProvider
from ophyd_async.sim import SimBlobDetector
from ophyd_async.testing import assert_emitted


@pytest.mark.parametrize("x_position,det_sum", [(0.0, 277544), (1.0, 506344)])
async def test_sim_blob_detector(
    RE: RunEngine, tmp_path, x_position: float, det_sum: int
):
    docs = defaultdict(list)
    RE.subscribe(lambda name, doc: docs[name].append(doc))
    path_provider = StaticPathProvider(StaticFilenameProvider("file"), tmp_path)
    det = SimBlobDetector(path_provider, name="det")
    det.pattern_generator.set_x(x_position)

    def plan():
        yield from bp.count([det], num=2)

    RE(plan())
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
            "shape": [1, 240, 320],
            "dtype": "array",
            "object_name": "det",
            "external": "STREAM:",
        },
        "det-sum": {
            "source": "sim://pattern-generator-hdf-file",
            "shape": [1,],
            "dtype": "number",
            "object_name": "det",
            "external": "STREAM:",
        },
    }
