"""Run the test-only Tango device servers this repo ships for testing ophyd-async.

No configuration beyond a prefix - every device name served is fixed (see the
module-level constants and `predict_trl`), so nothing is ever read back about what
got served: exactly how a real `softIoc -d some.db -m "PREFIX:"` never reports its
PV names back either, since they're fixed by the `.db` file and only the macro
prefix varies. Run directly with a plain PyTango interpreter, no ophyd-async client
machinery or real Tango database required:

    tango-venv/bin/python -m ophyd_async.tango.testing._tango_device_servers test/abc

It prints a readiness marker once serving, then blocks until stdin closes (or EOFs),
at which point it exits - the same shutdown mechanism
`ophyd_async.epics.testing.start_ioc`'s IOC subprocess uses (there, an explicit
`exit()` is written to the IOC shell's stdin first; here, nothing needs writing,
closing stdin is enough).

Serves `TestDevice`/`OneOfEverythingTangoDevice` (see `_tango.py`) - both plain
synchronous-green-mode devices, so (unlike `ophyd_async.tango.demo`'s device
servers, which need `GreenMode.Asyncio`) this is a single `MultiDeviceTestContext`
in a single process, no subprocess-splitting trick required. A test/demo topology
needing both catalogs (e.g. the system test suite) starts this module's servers
and `ophyd_async.tango.demo`'s independently, under the same prefix - see
`tests/system_tests_tango/conftest.py`.

`start_tango_device_servers` below is the one generic launcher for either
catalog - it just spawns argv and waits for a marker, so it doesn't care
whether that argv points at this module or `ophyd_async.tango.demo`'s.
`ophyd_async.tango.demo` doesn't duplicate it; it passes its own
`tango_device_servers_args()` here instead (see
`ophyd_async.tango.demo.__main__`).
"""

import sys
import zlib
from collections.abc import Sequence

from ophyd_async.testing import ManagedSubprocess, start_subprocess

_READY_MARKER = "TANGO_DEVICE_SERVERS_READY"

#: Default argv prefix used to host the device servers - the current Python
#: interpreter. Override to run against a separate PyTango-only venv's
#: interpreter, e.g. `["/path/to/pytango-venv/bin/python"]`.
DEFAULT_PYTHON_ARGS: Sequence[str] = (sys.executable,)

# Deterministic port: derived from the prefix so a caller can predict the TRL
# without anything being read back (see predict_trl). Chosen to sit below
# Linux's default ephemeral port range (typically 32768-60999) to minimise the
# (already small) chance of colliding with an unrelated OS-assigned port on the
# same machine, and to sit in a distinct range from
# `ophyd_async.tango.demo._tango_device_servers`'s so the two can be started
# under the same prefix without colliding.
_PORT_BASE = 20000
_PORT_RANGE = 10000

# Fixed device names served under any given prefix.
BASIC = "basic"
EVERYTHING = "everything"
ALL_DEVICE_NAMES = (BASIC, EVERYTHING)


def _port_for_prefix(prefix: str) -> int:
    """Deterministically derive the process port from `prefix`.

    Not Python's randomised `hash()` - this must be stable across
    processes/runs.
    """
    return _PORT_BASE + (zlib.crc32(prefix.encode()) % _PORT_RANGE)


def predict_trl(prefix: str, device_name: str) -> str:
    """Predict the TRL `tango_device_servers_args(prefix)` serves `device_name` at.

    `device_name` is one of the module-level constants above (e.g. `EVERYTHING`).
    Works without starting anything - the whole point of a fixed, prefix-derived
    port and fixed device names is that this is computable up front.
    """
    port = _port_for_prefix(prefix)
    return f"tango://127.0.0.1:{port}/{prefix}/{device_name}#dbase=no"


def tango_device_servers_args(prefix: str) -> list[str]:
    """Build the `-m ... <prefix>` argv for the fixed set of test-only device servers.

    Doesn't start anything - pass the result to `start_tango_device_servers`
    (which is where you can override which interpreter actually hosts the
    servers). There's no per-call configuration: every device this ends up
    serving has a name fixed by `predict_trl`.

    :param prefix: The domain/family prefix every served device's name is
        built from, e.g. via `generate_random_trl_prefix()`.
    """
    return ["-m", "ophyd_async.tango.testing._tango_device_servers", prefix]


def start_tango_device_servers(
    subprocess_args: Sequence[str],
    python_args: Sequence[str] = DEFAULT_PYTHON_ARGS,
) -> ManagedSubprocess:
    """Start a Tango device servers subprocess.

    :param subprocess_args: The `-m ... <prefix>` argv, built by
        `tango_device_servers_args`.
    :param python_args: Argv prefix used to host the device servers, defaulting
        to the current interpreter. Override to run against a separate
        PyTango-only venv's interpreter instead.

    Pins the readiness marker/stop command this catalog's server uses, so
    callers only ever need to supply argv.
    """
    return start_subprocess(
        [*python_args, *subprocess_args],
        _READY_MARKER,
        # MultiDeviceTestContext's own startup timeout below is 30s; give the
        # outer readiness wait some headroom above that rather than racing it.
        startup_timeout=45.0,
        stop_input=None,  # the __main__ block below exits on stdin EOF
    )


def _check_predicted_trl(ctx, prefix: str, device_name: str) -> None:
    """Canary check that predict_trl's assumptions still hold.

    If this ever fails, MultiDeviceTestContext's actual TRL shape has diverged
    from what predict_trl assumes - fail loudly here, at startup, rather than
    confusingly later when some other process tries to connect to a predicted
    TRL that was never actually being served.
    """
    actual = ctx.get_device_access(f"{prefix}/{device_name}")
    predicted = predict_trl(prefix, device_name)
    if actual != predicted:
        raise RuntimeError(f"Predicted TRL {predicted!r} doesn't match {actual!r}")


def _serve(prefix: str) -> None:
    """Serve TestDevice/OneOfEverythingTangoDevice, blocking until stdin closes."""
    from tango.test_context import MultiDeviceTestContext

    from ._tango import OneOfEverythingTangoDevice, TestDevice

    port = _port_for_prefix(prefix)
    configs = [
        {"class": TestDevice, "devices": [{"name": f"{prefix}/{BASIC}"}]},
        {
            "class": OneOfEverythingTangoDevice,
            "devices": [{"name": f"{prefix}/{EVERYTHING}"}],
        },
    ]
    with MultiDeviceTestContext(
        configs, host="127.0.0.1", port=port, process=False, timeout=30
    ) as ctx:
        _check_predicted_trl(ctx, prefix, EVERYTHING)
        print(_READY_MARKER, flush=True)
        sys.stdin.readline()  # block until our parent closes our stdin


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <prefix>")
    _serve(sys.argv[1])
