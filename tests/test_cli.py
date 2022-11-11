import subprocess
import sys

from ophyd_epics_devices import __version__


def test_cli_version():
    cmd = [sys.executable, "-m", "ophyd_epics_devices", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__
