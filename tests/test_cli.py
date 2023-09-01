import subprocess
import sys

from ophyd_async import __version__


def test_cli_version():
    cmd = [sys.executable, "-m", "ophyd_async", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__
