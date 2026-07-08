"""Launch this repo's Tango device server catalogs as managed subprocesses.

Kept separate from `_tango_device_servers.py` (this package's and
`ophyd_async.tango.demo`'s) deliberately: those two files are genuinely
standalone (zero `ophyd_async` imports, runnable from a bare PyTango venv),
and importing `ophyd_async.testing` here would break that if this lived in
the same file. `start_tango_device_servers` itself is catalog-agnostic - it
just spawns argv and waits for a marker - so it doesn't care whether that
argv points at `ophyd_async.tango.testing._tango_device_servers` or
`ophyd_async.tango.demo._tango_device_servers`; the catalog name just picks
which one.
"""

import sys
from collections.abc import Sequence
from typing import Literal

from ophyd_async.testing import ManagedSubprocess, start_subprocess

from ._tango_device_servers import (
    tango_device_servers_args as _testing_tango_device_servers_args,
)

Catalog = Literal["testing", "demo"]

# Every catalog's __main__ prints this same literal once serving (see each
# _tango_device_servers.py's own copy - duplicated there rather than imported
# from here, since those files must stay ophyd_async-import-free).
_READY_MARKER = "TANGO_DEVICE_SERVERS_READY"

#: Default argv prefix used to host the device servers - the current Python
#: interpreter. Override to run against a separate PyTango-only venv's
#: interpreter, e.g. `["/path/to/pytango-venv/bin/python"]`.
DEFAULT_PYTHON_ARGS: Sequence[str] = (sys.executable,)


def _args_for(catalog: Catalog, prefix: str) -> list[str]:
    if catalog == "testing":
        return _testing_tango_device_servers_args(prefix)
    if catalog == "demo":
        from ophyd_async.tango.demo._tango_device_servers import (
            tango_device_servers_args as demo_args,
        )

        return demo_args(prefix)
    raise ValueError(f"Unknown catalog {catalog!r}, expected 'testing' or 'demo'")


def start_tango_device_servers(
    catalog: Catalog,
    prefix: str,
    python_args: Sequence[str] = DEFAULT_PYTHON_ARGS,
) -> ManagedSubprocess:
    """Start a Tango device servers subprocess.

    :param catalog: Which fixed device catalog to serve - `"testing"`
        (`ophyd_async.tango.testing`'s `basic`/`everything`) or `"demo"`
        (`ophyd_async.tango.demo`'s motor/channel/detector).
    :param prefix: The domain/family prefix every served device's name is
        built from, e.g. via `generate_random_trl_prefix()`.
    :param python_args: Argv prefix used to host the device servers, defaulting
        to the current interpreter. Override to run against a separate
        PyTango-only venv's interpreter instead.

    Pins the readiness marker/stop command every catalog's server uses
    (identical for both - see each `_tango_device_servers.py`'s own copy), so
    callers only ever need to name the catalog and supply a prefix.
    """
    args = _args_for(catalog, prefix)
    return start_subprocess(
        [*python_args, *args],
        _READY_MARKER,
        # MultiDeviceTestContext's own startup timeout is 30s; give the outer
        # readiness wait some headroom above that rather than racing it.
        startup_timeout=45.0,
        stop_input=None,  # each catalog's __main__ block exits on stdin EOF
    )
