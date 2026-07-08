"""Run every Tango device server this repo ships for testing/demoing ophyd-async.

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

Used identically by the test suite and the `ophyd_async.tango.demo` tutorial, via
`tango_device_servers_args()` + `start_tango_device_servers` - see
`tests/system_tests_tango/conftest.py` and `ophyd_async.tango.demo.__main__`.

Under the hood this spawns a second, grandchild OS process (`--async-devices`, below)
rather than serving everything from one process: `TestDevice`/
`OneOfEverythingTangoDevice` are plain synchronous-green-mode devices, while the
`Demo*Device` classes need `GreenMode.Asyncio` (for their `asyncio.sleep`-based
movement/acquisition simulation). PyTango only allows one green mode per device
server process - two things were tried and rejected before landing on two processes:
forcing everything into one green mode (changed how `OneOfEverythingTangoDevice`'s
dynamically-created array attributes reported their dtype to clients, breaking type
checks unrelated to green mode), and two `MultiDeviceTestContext`s in one process
(segfaults - apparently genuinely unsupported by the underlying omniORB/cppTango
bindings, not just a Python-level restriction). None of this is visible from outside
this module - callers still get one prefix, one predictable set of TRLs, one argv.
"""

import subprocess
import sys
import zlib
from collections.abc import Sequence

import tango

from ophyd_async.testing import ManagedSubprocess, start_subprocess

_READY_MARKER = "TANGO_DEVICE_SERVERS_READY"
_ASYNC_DEVICES_FLAG = "--async-devices"

#: Default argv prefix used to host the device servers - the current Python
#: interpreter. Override to run against a separate PyTango-only venv's
#: interpreter, e.g. `["/path/to/pytango-venv/bin/python"]`.
DEFAULT_PYTHON_ARGS: Sequence[str] = (sys.executable,)

# Deterministic port range: derived from the prefix so a caller can predict the
# TRL without anything being read back (see _sync_port_for_prefix/predict_trl).
# Chosen to sit below Linux's default ephemeral port range (typically
# 32768-60999) to minimise the (already small) chance of colliding with an
# unrelated OS-assigned port on the same machine. Two ports per prefix - see
# module docstring for why.
_PORT_BASE = 20000
_PORT_RANGE = 10000 - 1  # -1: leave room for the +1 second port below

# Fixed device names served under any given prefix.
BASIC = "basic"
EVERYTHING = "everything"
MOTOR_X = "motor-x"
MOTOR_Y = "motor-y"
CHANNEL_1 = "channel-1"
CHANNEL_2 = "channel-2"
CHANNEL_3 = "channel-3"
DETECTOR = "detector"
CHANNEL_NAMES = (CHANNEL_1, CHANNEL_2, CHANNEL_3)
NUM_CHANNELS = len(CHANNEL_NAMES)

# Synchronous-green-mode devices, served by this process on the base port...
SYNC_DEVICE_NAMES = (BASIC, EVERYTHING)
# ...and GreenMode.Asyncio devices, served by the --async-devices grandchild
# process on base port + 1.
ASYNC_DEVICE_NAMES = (MOTOR_X, MOTOR_Y, *CHANNEL_NAMES, DETECTOR)
ALL_DEVICE_NAMES = (*SYNC_DEVICE_NAMES, *ASYNC_DEVICE_NAMES)


def _sync_port_for_prefix(prefix: str) -> int:
    """Deterministically derive the sync-process port from `prefix`.

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
    port = _sync_port_for_prefix(prefix)
    if device_name in ASYNC_DEVICE_NAMES:
        port += 1
    return f"tango://127.0.0.1:{port}/{prefix}/{device_name}#dbase=no"


def tango_device_servers_args(
    prefix: str, python_args: Sequence[str] = DEFAULT_PYTHON_ARGS
) -> list[str]:
    """Build the argv for the fixed set of Tango device servers.

    Serves the repo's whole test/demo catalog under `prefix`.

    Doesn't start anything - pass the result to `start_tango_device_servers`.
    There's no per-call configuration: every device this ends up serving has a
    name fixed by `predict_trl`.

    :param prefix: The domain/family prefix every served device's name is
        built from, e.g. via `generate_random_trl_prefix()`.
    :param python_args: Argv prefix used to host the device servers, defaulting
        to the current interpreter. Override to run against a separate
        PyTango-only venv's interpreter instead.
    """
    return [
        *python_args,
        "-m",
        "ophyd_async.tango.testing._tango_device_servers",
        prefix,
    ]


def start_tango_device_servers(subprocess_args: Sequence[str]) -> ManagedSubprocess:
    """Start a Tango device servers subprocess, built by `tango_device_servers_args`.

    Pins the readiness marker/stop command every catalog this module serves
    uses, so callers only ever need to supply argv.
    """
    return start_subprocess(
        subprocess_args,
        _READY_MARKER,
        # MultiDeviceTestContext's own startup timeout below is 30s; give the
        # outer readiness wait some headroom above that rather than racing it.
        startup_timeout=45.0,
        stop_input=None,  # the __main__ block below exits on stdin EOF
    )


def _wire_demo_devices(prefix: str) -> None:
    """Connect the demo channel/detector devices to their motors/channels.

    Done here, once, so `tango_device_servers_args` is genuinely
    standalone-runnable with no external orchestration required (unlike the old
    per-caller wiring this replaced).
    """
    for channel_name in CHANNEL_NAMES:
        proxy = tango.DeviceProxy(predict_trl(prefix, channel_name))
        proxy.locator_x = predict_trl(prefix, MOTOR_X)
        proxy.locator_y = predict_trl(prefix, MOTOR_Y)
        proxy.connect_devices()
    detector_proxy = tango.DeviceProxy(predict_trl(prefix, DETECTOR))
    detector_proxy.locators = [predict_trl(prefix, name) for name in CHANNEL_NAMES]
    detector_proxy.connect_devices()


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


def _serve_sync_devices(prefix: str) -> None:
    """Serve TestDevice/OneOfEverythingTangoDevice (default green mode).

    Also starts the --async-devices grandchild for the rest, blocking until our
    own stdin closes.
    """
    from tango.test_context import MultiDeviceTestContext

    from ._tango import OneOfEverythingTangoDevice, TestDevice

    port = _sync_port_for_prefix(prefix)
    configs = [
        {"class": TestDevice, "devices": [{"name": f"{prefix}/{BASIC}"}]},
        {
            "class": OneOfEverythingTangoDevice,
            "devices": [{"name": f"{prefix}/{EVERYTHING}"}],
        },
    ]

    # Start the grandchild before entering our own MultiDeviceTestContext, so its
    # (independent) startup timeout runs concurrently with ours rather than after.
    # sys.executable here is whatever interpreter is actually running this
    # process, so a caller's python_args override to tango_device_servers_args
    # is naturally inherited without needing to thread it through explicitly.
    grandchild = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ophyd_async.tango.testing._tango_device_servers",
            prefix,
            _ASYNC_DEVICES_FLAG,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        with MultiDeviceTestContext(
            configs, host="127.0.0.1", port=port, process=False, timeout=30
        ) as ctx:
            _check_predicted_trl(ctx, prefix, EVERYTHING)

            # Wait for the grandchild's own readiness marker on its stdout.
            output = ""
            while _READY_MARKER not in output:
                line = grandchild.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    raise RuntimeError(
                        f"--async-devices grandchild exited before becoming "
                        f"ready:\n{output}"
                    )
                output += line

            _wire_demo_devices(prefix)

            print(_READY_MARKER, flush=True)
            sys.stdin.readline()  # block until our parent closes our stdin
    finally:
        grandchild.communicate(None, timeout=10)


def _serve_async_devices(prefix: str) -> None:
    """Serve the Demo*Device classes (GreenMode.Asyncio).

    Blocks until our own stdin closes. Only ever launched as a grandchild of
    _serve_sync_devices.
    """
    from tango import GreenMode
    from tango.test_context import MultiDeviceTestContext

    from ._tango import (
        DemoMotorDevice,
        DemoMultiChannelDetectorDevice,
        DemoPointDetectorChannelDevice,
    )

    port = _sync_port_for_prefix(prefix) + 1
    configs = [
        {
            "class": DemoMotorDevice,
            "devices": [
                {"name": f"{prefix}/{MOTOR_X}"},
                {"name": f"{prefix}/{MOTOR_Y}"},
            ],
        },
        {
            "class": DemoPointDetectorChannelDevice,
            "devices": [
                {"name": f"{prefix}/{name}", "properties": {"channel": i}}
                for i, name in enumerate(CHANNEL_NAMES, start=1)
            ],
        },
        {
            "class": DemoMultiChannelDetectorDevice,
            "devices": [
                {
                    "name": f"{prefix}/{DETECTOR}",
                    "properties": {"channels": NUM_CHANNELS},
                }
            ],
        },
    ]
    with MultiDeviceTestContext(
        configs,
        host="127.0.0.1",
        port=port,
        process=False,
        timeout=30,
        green_mode=GreenMode.Asyncio,
    ) as ctx:
        _check_predicted_trl(ctx, prefix, DETECTOR)
        print(_READY_MARKER, flush=True)
        sys.stdin.readline()  # block until our parent closes our stdin


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit(f"Usage: {sys.argv[0]} <prefix> [{_ASYNC_DEVICES_FLAG}]")
    if len(sys.argv) == 3 and sys.argv[2] == _ASYNC_DEVICES_FLAG:
        _serve_async_devices(sys.argv[1])
    else:
        _serve_sync_devices(sys.argv[1])
