import subprocess
import sys

import pytest

from ophyd_async import __version__


@pytest.mark.timeout(3)
def test_cli_version():
    cmd = [sys.executable, "-m", "ophyd_async", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__
