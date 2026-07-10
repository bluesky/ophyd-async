"""Run an EPICS IOC backing the `ophyd_async.epics.demo` tutorial.

Genuinely standalone: nothing in this file imports anything from
`ophyd_async` - only stdlib. That's deliberate, not incidental: it means this
file can be copied into (or run from) a separate EPICS-only venv that
doesn't have `ophyd_async` installed at all, exactly as a real `softIoc`
binary doesn't need whatever's launching it to be Python.

Serves an X/Y sample stage plus a multi-channel point detector (see
`_demo_ioc_args`). Run directly with a plain Python interpreter:

    python /path/to/ophyd_async/epics/demo/_ioc.py \
        <prefix> <num_channels> [--softioc ARG ...]
"""

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).absolute().parent

#: Default argv appended after a module's own args - the bundled
#: `epicscorelibs.ioc` module. Override (e.g. to `["softIoc"]`) to run
#: against a real EPICS installation's `softIoc` binary instead. Hardcoded
#: again, independently, in `ophyd_async.epics.testing._ioc` - see this
#: module's own docstring for why.
DEFAULT_SOFTIOC_ARGS = (sys.executable, "-m", "epicscorelibs.ioc")


def _demo_ioc_args(prefix: str, num_channels: int) -> list[str]:
    """Build the `-m macro -d db.db [...]` argv softIoc/epicscorelibs.ioc expect.

    Serves an X/Y sample stage plus a multi-channel point detector with
    `num_channels` channels, all under `prefix`.
    """
    motor_db = str(HERE / "motor.db")
    detector_db = str(HERE / "point_detector.db")
    channel_db = str(HERE / "point_detector_channel.db")
    argv = [
        "-m", f"P={prefix}STAGE:X:", "-d", motor_db,
        "-m", f"P={prefix}STAGE:Y:", "-d", motor_db,
        "-m", f"P={prefix}DET:", "-d", detector_db,
    ]  # fmt: skip
    for i in range(1, num_channels + 1):
        macro = f"P={prefix}DET:,CHANNEL={i},X={prefix}STAGE:X:,Y={prefix}STAGE:Y:"
        argv += ["-m", macro, "-d", channel_db]
    return argv


if __name__ == "__main__":
    # --softioc overrides which executable actually hosts the IOC,
    # defaulting to DEFAULT_SOFTIOC_ARGS - e.g. `python _ioc.py demo: 3
    # --softioc softIoc` to use a real EPICS installation instead of the
    # bundled epicscorelibs.ioc.
    parser = argparse.ArgumentParser(
        description="Serve an IOC for a sample stage and point detector."
    )
    parser.add_argument("prefix", help="Prefix every served PV's macro is built from")
    parser.add_argument(
        "num_channels", type=int, help="Number of point detector channels to create"
    )
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
    ioc_args = _demo_ioc_args(args.prefix, args.num_channels)
    sys.exit(subprocess.run([*softioc_args, *ioc_args]).returncode)
