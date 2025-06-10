from collections import defaultdict

import bluesky.plans as bp
from bluesky import RunEngine

from ophyd_async.core import StaticPathProvider
from ophyd_async.sim import NullPatternGenerator, SimBlobDetector
from ophyd_async.testing import assert_emitted


async def test_null_pattern_generator_does_nothing(RE: RunEngine):
    pattern_generator = NullPatternGenerator()
    path_provider = StaticPathProvider(lambda _: "null_file", "/")
    detector = SimBlobDetector(
        path_provider, pattern_generator=pattern_generator, name="det"
    )
    docs = defaultdict(list)
    RE.subscribe(lambda name, doc: docs[name].append(doc))
    RE(bp.count([detector], num=2))

    assert_emitted(
        docs, start=1, descriptor=1, stream_resource=2, stream_datum=4, event=2, stop=1
    )
    assert docs["descriptor"][0]["data_keys"] == {
        "det": {
            "source": "sim://pattern-generator-hdf-file",
            "shape": [1, 240, 320],
            "dtype": "array",
            "dtype_numpy": "|u1",
            "object_name": "det",
            "external": "STREAM:",
        },
        "det-sum": {
            "source": "sim://pattern-generator-hdf-file",
            "shape": [],
            "dtype": "number",
            "dtype_numpy": "<i8",
            "object_name": "det",
            "external": "STREAM:",
        },
    }
