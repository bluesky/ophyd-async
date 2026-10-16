"""The one fixed EPICS test-only IOC catalog this repo ships.

Genuinely standalone: nothing in this file imports anything from
`ophyd_async` - only stdlib. That's deliberate, not incidental: it means this
file can be copied into (or run from) a separate EPICS-only venv that
doesn't have `ophyd_async` installed at all, exactly as a real `softIoc`
binary doesn't need whatever's launching it to be Python. The `.db` file
names/paths below are duplicated from `ophyd_async.epics.testing`'s own
`CA_PVA_RECORDS`/`PVA_RECORDS`/`PVI_NESTED_RECORDS` for the same reason.

Serves `ca:`/`pva:`/`nested:` sub-topologies under whatever prefix you give
it (see `_testing_ioc_args`). Run directly with a plain Python interpreter:

    python /path/to/ophyd_async/epics/testing/_ioc.py <prefix> [--softioc ARG ...]
"""

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).absolute().parent

#: Default argv appended after a module's own args - the bundled
#: `epicscorelibs.ioc` module. Hardcoded again, independently, in
#: `ophyd_async.epics.demo._ioc`.
DEFAULT_SOFTIOC_ARGS = (sys.executable, "-m", "epicscorelibs.ioc")


def _testing_ioc_args(prefix: str) -> list[str]:
    """Build the `-m macro -d db.db [...]` argv softIoc/epicscorelibs.ioc expect.

    Serves `ca:`/`pva:`/`nested:` sub-topologies under `prefix`:

    - `ca:`: `_epics_test_ca_records.db`, backing `EpicsTestCaDevice`.
    - `pva:`: `_epics_test_ca_records.db` *and* `_epics_test_pva_records.db`
      (loaded as two separate `-d`s under the same macro, rather than having
      the pva db `include` the ca one - easier to see what's actually being
      loaded), backing `EpicsTestPvaDevice`/`EpicsTestPviDevice`.
    - `nested:`: `_pvi_nested_records.db`, backing `EpicsTestPviNestedDevice`/
      `EpicsTestPviLeafDevice`/`EpicsTestPviNestedDeviceMissingChild`.
    """
    ca_prefix = f"{prefix}ca:"
    pva_prefix = f"{prefix}pva:"
    nested_prefix = f"{prefix}nested:"
    ca_db = str(HERE / "_epics_test_ca_records.db")
    pva_db = str(HERE / "_epics_test_pva_records.db")
    nested_db = str(HERE / "_pvi_nested_records.db")
    return [
        "-m", f"device={ca_prefix}", "-d", ca_db,
        "-m", f"device={pva_prefix}", "-d", ca_db,
        "-m", f"device={pva_prefix}", "-d", pva_db,
        "-m", f"device={nested_prefix}", "-d", nested_db,
    ]  # fmt: skip


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Serve the fixed EPICS test-only IOC catalog (ca:/pva:/nested:)."
    )
    parser.add_argument("prefix", help="Prefix every served PV's macro is built from")
    parser.add_argument(
        "--softioc",
        nargs="*",
        metavar="ARG",
        help="Executable (+ args) that hosts the IOC, defaulting to the bundled "
        "epicscorelibs.ioc - e.g. '--softioc softIoc' to use a real EPICS "
        "installation",
    )
    args = parser.parse_args()
    softioc_args = args.softioc or DEFAULT_SOFTIOC_ARGS
    ioc_args = _testing_ioc_args(args.prefix)
    sys.exit(subprocess.run([*softioc_args, *ioc_args]).returncode)
