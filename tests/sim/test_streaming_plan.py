from collections import defaultdict
from typing import Dict
import bluesky.plan_stubs as bps

from bluesky.run_engine import RunEngine
from ophyd_async.sim.SimPatternDetector import SimDetector
from bluesky import plans as bp


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

    # def basic_plan():
    #     yield from bps.stage_all(sim_pattern_detector)

    #     yield from bps.prepare(1, wait=True)

    #     # prepare detectors second.
    #     yield from bps.prepare(sim_pattern_detector, wait=True)

    #     sim_pattern_detector.controller.disarm.assert_called_once

    #     yield from bps.open_run()

    #     yield from bps.kickoff(sim_pattern_detector)

    #     yield from bps.complete(sim_pattern_detector, wait=False, group="complete")

    #     # Manually increment the index as if a frame was taken
    #     sim_pattern_detector.writer.index += 1

    #     done = False
    #     while not done:
    #         try:
    #             yield from bps.wait(group="complete", timeout=0.5)
    #         except TimeoutError:
    #             pass
    #         else:
    #             done = True
    #         yield from bps.collect(
    #             sim_pattern_detector,
    #             stream=True,
    #             return_payload=False,
    #             name="main_stream",
    #         )
    #         yield from bps.sleep(0.01)
    #     yield from bps.wait(group="complete")

    #     yield from bps.close_run()

    #     yield from bps.unstage_all(sim_pattern_detector)
    #     assert sim_pattern_detector.controller.disarm.called

    # RE(basic_plan())
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
