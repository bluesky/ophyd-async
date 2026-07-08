"""Generic EPICS IOC-hosting launcher - builds no topology of its own.

Every ophyd_async-provided EPICS test/demo IOC launch goes through this one
file *by path* (not `-m ophyd_async...`), via `ophyd_async.epics.testing.start_ioc`
- so there's no separate "does this even work standalone" code path to keep
correct: the exact subprocess invocation the test suite exercises on every run
is the one a human would type by hand:

    python /path/to/ophyd_async/epics/testing/_ioc.py \
        <softioc_arg0> <softioc_arg1> ... -- -m <macros> -d <db.db> [-m ... -d ...]

Everything before `--` is the executable that actually hosts the IOC
(defaulting to the bundled `epicscorelibs.ioc` - see
`ophyd_async.epics.testing.DEFAULT_SOFTIOC_ARGS`); everything after is handed
to it verbatim (the `softIoc`/`epicscorelibs.ioc` `-m macro -d db.db`
convention). This file just re-execs into that combination - the actual IOC
hosting is entirely `epicscorelibs.ioc`'s/`softIoc`'s job, neither of which
needs `ophyd_async` (this file doesn't import it either, though unlike the
Tango device servers there's no separate-venv motivation for that here - it
falls out for free from this file only ever forwarding argv verbatim).
"""

import subprocess
import sys

if __name__ == "__main__":
    if "--" not in sys.argv:
        raise SystemExit(
            f"Usage: {sys.argv[0]} <softioc_args...> -- <-m macro -d db.db ...>"
        )
    sep = sys.argv.index("--")
    softioc_args, ioc_argv = sys.argv[1:sep], sys.argv[sep + 1 :]
    sys.exit(subprocess.run([*softioc_args, *ioc_argv]).returncode)
