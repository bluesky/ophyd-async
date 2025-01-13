import importlib
import re
import time
from unittest.mock import patch

import pytest
from bluesky.run_engine import RunEngine

EXPECTED = """
+-----------+------------+-----------------------+-----------------------+----------------------+----------------------+----------------------+
|   seq_num |       time | stage-x-user_readback | stage-y-user_readback | det1-channel-1-value | det1-channel-2-value | det1-channel-3-value |
+-----------+------------+-----------------------+-----------------------+----------------------+----------------------+----------------------+
|         1 | 10:41:18.8 |                 1.000 |                 1.000 |                  711 |                  678 |                  650 |
|         2 | 10:41:18.9 |                 1.000 |                 1.500 |                  831 |                  797 |                  769 |
|         3 | 10:41:19.1 |                 1.000 |                 2.000 |                  921 |                  887 |                  859 |
|         4 | 10:41:19.2 |                 1.500 |                 1.000 |                  870 |                  869 |                  868 |
|         5 | 10:41:19.3 |                 1.500 |                 1.500 |                  986 |                  986 |                  985 |
|         6 | 10:41:19.4 |                 1.500 |                 2.000 |                  976 |                  975 |                  974 |
|         7 | 10:41:19.6 |                 2.000 |                 1.000 |                  938 |                  917 |                  898 |
|         8 | 10:41:19.7 |                 2.000 |                 1.500 |                  954 |                  933 |                  914 |
|         9 | 10:41:19.8 |                 2.000 |                 2.000 |                  761 |                  740 |                  722 |
+-----------+------------+-----------------------+-----------------------+----------------------+----------------------+----------------------+
"""  # noqa: E501


# https://regex101.com/r/KvLj7t/1
SCAN_LINE = re.compile(
    r"^\| *(\d+) \|[^\|]*\| *(\d*.\d*) \| *(\d*.\d*) \| *(\d*) \| *(\d*) \| *(\d*) \|$",
    re.M,
)


@pytest.fixture
def expected_scan_output():
    # TODO: get this from md file
    matches = SCAN_LINE.findall(EXPECTED)
    assert len(matches) == 9
    yield matches


@pytest.mark.parametrize("module", ["ophyd_async.sim", "ophyd_async.epics.demo"])
def test_implementing_devices(module, capsys, expected_scan_output):
    with patch("bluesky.run_engine.autoawait_in_bluesky_event_loop") as autoawait:
        main = importlib.import_module(f"{module}.__main__")
        autoawait.assert_called_once_with()
    RE: RunEngine = main.RE
    for motor in [main.stage.x, main.stage.y]:
        RE(main.bps.mv(motor.velocity, 1000))
    start = time.monotonic()
    RE(main.bp.grid_scan([main.det1], main.stage.x, 1, 2, 3, main.stage.y, 1, 2, 3))
    assert time.monotonic() - start == pytest.approx(2.0, abs=1.0)
    captured = capsys.readouterr()
    assert captured.err == ""
    assert SCAN_LINE.findall(captured.out) == expected_scan_output
