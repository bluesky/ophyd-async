import importlib
import re
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from aioca import purge_channel_caches
from bluesky.run_engine import RunEngine

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
@pytest.mark.timeout(20)
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

        # If we are testing the EPICS demo, we need to stop the IOC and purge caches
        # to avoid CA virtual circuit disconnect errors.
        if module == "ophyd_async.epics.demo":
            purge_channel_caches()
            main.ioc.stop()
