from collections import defaultdict

from bluesky import plans as bp
from bluesky.run_engine import RunEngine

from ophyd_async.core import assert_emitted
from ophyd_async.plan_stubs import ensure_connected
from ophyd_async.sim.demo import PatternDetector


# NOTE the async operations with h5py are non-trival
# because of lack of native support for async operations
# see https://github.com/h5py/h5py/issues/837
async def test_streaming_plan(RE: RunEngine, sim_pattern_detector: PatternDetector):
    names = []
    docs = []

    def append_and_print(name, doc):
        names.append(name)
        docs.append(doc)

    RE.subscribe(append_and_print)

    def plan():
        yield from ensure_connected(sim_pattern_detector, mock=True)
        yield from bp.count([sim_pattern_detector], num=1)

    RE(plan())

    # NOTE - double resource because double stream
    assert names == [
        "start",
        "descriptor",
        "stream_resource",
        "stream_resource",
        "stream_datum",
        "stream_datum",
        "event",
        "stop",
    ]
    await sim_pattern_detector.writer.close()


async def test_plan(RE: RunEngine, sim_pattern_detector: PatternDetector):
    docs = defaultdict(list)

    def plan():
        yield from ensure_connected(sim_pattern_detector, mock=True)
        yield from bp.count([sim_pattern_detector])

    RE(plan(), lambda name, doc: docs[name].append(doc))

    assert_emitted(
        docs, start=1, descriptor=1, stream_resource=2, stream_datum=2, event=1, stop=1
    )
