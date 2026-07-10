"""System tests for verifying Transport not available error when aioca/p4p missing."""

import subprocess
import sys
from pathlib import Path

import pytest

# Path to the helper script
HELPER_SCRIPT = Path(__file__).parent / "no_transport_helper.py"


@pytest.mark.parametrize(
    "block_protocols,use_protocol",
    [
        (["ca"], "ca"),
        (["pva"], "pva"),
        (["ca", "pva"], "ca"),
        (["ca", "pva"], "pva"),
    ],
)
def test_transport_not_available_error(block_protocols, use_protocol):
    flags = [f"--block-{protocol}" for protocol in block_protocols]
    pv_name = f"{use_protocol}://TEST-PV"
    result = subprocess.run(
        [sys.executable, str(HELPER_SCRIPT), *flags, pv_name],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "NotImplementedError" in result.stderr
    assert "epics_signal_rw" in result.stderr
    assert result.stderr.endswith(
        f"Protocol {use_protocol} not available, "
        f"did you `pip install ophyd_async[{use_protocol}]`?\n"
    )
