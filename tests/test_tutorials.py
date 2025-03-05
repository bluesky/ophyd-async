import importlib
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

import bluesky.plan_stubs as bps
import bluesky.preprocessors as bpp
import h5py
import pytest
from bluesky.run_engine import RunEngine

from ophyd_async.core import TriggerInfo
from ophyd_async.sim import FlySimMotorInfo
from ophyd_async.testing import assert_emitted

# https://regex101.com/r/KvLj7t/1
SCAN_LINE = re.compile(
    r"^\| *(\d+) \|[^\|]*\| *(\d*.\d*) \| *(\d*.\d*) \| *(\d*) \| *(\d*) \| *(\d*) \|$",
    re.M,
)


@pytest.fixture
def expected_scan_output():
    tutorial_text = (
        Path(__file__).absolute().parent.parent
        / "docs"
        / "tutorials"
        / "implementing-devices.md"
    ).read_text()
    matches = SCAN_LINE.findall(tutorial_text)
    assert len(matches) == 9
    yield matches


@pytest.mark.parametrize("module", ["ophyd_async.sim", "ophyd_async.epics.demo"])
def test_implementing_devices(module, capsys, expected_scan_output):
    with patch("matplotlib.get_backend"):
        with patch("bluesky.run_engine.autoawait_in_bluesky_event_loop") as autoawait:
            main = importlib.import_module(f"{module}.__main__")
            autoawait.assert_called_once_with()
        # We want the text output of the best effort callback, but the plotting takes
        # too much time for CI, even if headless, so disable it
        main.bec._set_up_plots = lambda *args, **kwargs: None
        RE: RunEngine = main.RE
        for motor in [main.stage.x, main.stage.y]:
            RE(main.bps.mv(motor.velocity, 1000))
        start = time.monotonic()
        RE(main.bp.grid_scan([main.pdet], main.stage.x, 1, 2, 3, main.stage.y, 2, 3, 3))
        assert time.monotonic() - start == pytest.approx(2.5, abs=2.0)
        captured = capsys.readouterr()
        assert captured.err == ""
        assert SCAN_LINE.findall(captured.out) == expected_scan_output


def test_flyscanning_devices(capsys):
    with patch("matplotlib.get_backend"):
        with patch("bluesky.run_engine.autoawait_in_bluesky_event_loop"):
            main = importlib.import_module("ophyd_async.sim.__main__")
        # We want the text output of the best effort callback, but the plotting takes
        # too much time for CI, even if headless, so disable it
        main.bec._set_up_plots = lambda *args, **kwargs: None
        RE: RunEngine = main.RE

        @bpp.stage_decorator([main.bdet])
        @bpp.monitor_during_decorator([main.stage.x.user_readback])
        @bpp.run_decorator()
        def fly_plan():
            # Move to the start
            yield from bps.prepare(main.bdet, TriggerInfo(number_of_triggers=7))
            yield from bps.abs_set(main.stage.y.velocity, 0)
            yield from bps.abs_set(main.stage.y, 0)
            yield from bps.prepare(
                main.stage.x, FlySimMotorInfo(cv_start=1, cv_end=2, cv_time=0.7)
            )
            yield from bps.wait()
            yield from bps.declare_stream(main.bdet, name="primary")
            # Kickoff stage and wait until at velocity
            yield from bps.kickoff(main.stage.x, wait=True)
            # Kickoff the detector
            yield from bps.kickoff(main.bdet, wait=True)
            # Collect the data
            yield from bps.collect_while_completing(
                flyers=[main.stage.x, main.bdet], dets=[main.bdet], flush_period=0.42
            )

        docs = defaultdict(list)
        RE.subscribe(lambda name, doc: docs[name].append(doc))
        start = time.monotonic()
        RE(fly_plan())
        assert time.monotonic() - start == pytest.approx(1.7, abs=0.2)
        captured = capsys.readouterr()
        assert captured.err == ""
        # assert captured.out == ""
        assert_emitted(
            docs,
            start=1,
            descriptor=2,
            event=19,
            stream_resource=2,
            stream_datum=4,
            stop=1,
        )
        assert [d["data"]["stage-x"] for d in docs["event"]] == []
        path = docs["stream_resource"][0]["uri"].split("://localhost")[-1]
        if os.name == "nt":
            path = path.lstrip("/")
        h5file = h5py.File(path)
        assert list(h5file["/entry/sum"]) == [
            524952,
            538800,
            547064,
            549656,
            547020,
            538668,
            524808,
        ]
