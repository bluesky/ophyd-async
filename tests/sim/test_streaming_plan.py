from collections import defaultdict
from typing import Dict

from bluesky import plans as bp
from bluesky.run_engine import RunEngine

from ophyd_async.sim.SimPatternDetector import SimDetector


def assert_emitted(docs: Dict[str, list], **numbers: int):
    assert list(docs) == list(numbers)
    assert {name: len(d) for name, d in docs.items()} == numbers


async def test_streaming_plan(RE: RunEngine, sim_pattern_detector: SimDetector):
    names = []
    docs = []

    def append_and_print(name, doc):
        names.append(name)
        docs.append(doc)

    RE.subscribe(append_and_print)

    RE(bp.count([sim_pattern_detector], num=1))

    print(names)
    assert names == [
        "start",
        "descriptor",
        "stream_resource",
        "stream_datum",
        "stream_resource",
        "stream_datum",
        "event",
        "stop",
    ]


def test_plan(RE: RunEngine, sim_pattern_detector: SimDetector):
    docs = defaultdict(list)
    RE(bp.count([sim_pattern_detector]), lambda name, doc: docs[name].append(doc))
    assert_emitted(docs, start=1, descriptor=1, resource=1, datum=1, event=1, stop=1)
    assert docs["event"][0]["data"] == defaultdict(list, {"sim_pattern_detector": [1]})
