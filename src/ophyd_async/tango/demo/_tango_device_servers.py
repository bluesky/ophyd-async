"""Run the Tango device servers backing the `ophyd_async.tango.demo` tutorial.

No configuration beyond a prefix - every device name served is fixed (see the
module-level constants and `predict_trl`), so nothing is ever read back about what
got served: exactly how a real `softIoc -d some.db -m "PREFIX:"` never reports its
PV names back either, since they're fixed by the `.db` file and only the macro
prefix varies. Run directly with a plain PyTango interpreter, no ophyd-async client
machinery or real Tango database required:

    tango-venv/bin/python -m ophyd_async.tango.demo._tango_device_servers test/abc

It prints a readiness marker once serving, then blocks until stdin closes (or EOFs),
at which point it exits. To actually launch it as a managed subprocess, pass
`tango_device_servers_args()` to `ophyd_async.tango.testing.start_tango_device_servers`
- that generic launcher isn't duplicated here, since it doesn't care which
device catalog its argv points at (see that function's docstring).

Serves `DemoMotorDevice`/`DemoMultiChannelDetectorDevice`/
`DemoPointDetectorChannelDevice` (see `_tango.py`), which all need
`GreenMode.Asyncio` for their `asyncio.sleep`-based movement/acquisition
simulation - a separate module/process from
`ophyd_async.tango.testing`'s test-only device servers (which use the default
sync green mode - PyTango only allows one green mode per device server
process). A topology needing both catalogs (e.g. the system test suite) starts
this module's servers and `ophyd_async.tango.testing`'s independently, under
the same prefix - see `tests/system_tests_tango/conftest.py`.
"""

import sys
import zlib

import tango

_READY_MARKER = "TANGO_DEVICE_SERVERS_READY"

# Deterministic port: derived from the prefix so a caller can predict the TRL
# without anything being read back (see predict_trl). Chosen to sit below
# Linux's default ephemeral port range (typically 32768-60999) to minimise the
# (already small) chance of colliding with an unrelated OS-assigned port on the
# same machine, and to sit in a distinct range from
# `ophyd_async.tango.testing._tango_device_servers`'s so the two can be started
# under the same prefix without colliding.
_PORT_BASE = 30000
_PORT_RANGE = 10000

# Fixed device names served under any given prefix.
MOTOR_X = "motor-x"
MOTOR_Y = "motor-y"
CHANNEL_1 = "channel-1"
CHANNEL_2 = "channel-2"
CHANNEL_3 = "channel-3"
DETECTOR = "detector"
CHANNEL_NAMES = (CHANNEL_1, CHANNEL_2, CHANNEL_3)
NUM_CHANNELS = len(CHANNEL_NAMES)
ALL_DEVICE_NAMES = (MOTOR_X, MOTOR_Y, *CHANNEL_NAMES, DETECTOR)


def _port_for_prefix(prefix: str) -> int:
    """Deterministically derive the process port from `prefix`.

    Not Python's randomised `hash()` - this must be stable across
    processes/runs.
    """
    return _PORT_BASE + (zlib.crc32(prefix.encode()) % _PORT_RANGE)


def predict_trl(prefix: str, device_name: str) -> str:
    """Predict the TRL `tango_device_servers_args(prefix)` serves `device_name` at.

    `device_name` is one of the module-level constants above (e.g. `DETECTOR`).
    Works without starting anything - the whole point of a fixed, prefix-derived
    port and fixed device names is that this is computable up front.
    """
    port = _port_for_prefix(prefix)
    return f"tango://127.0.0.1:{port}/{prefix}/{device_name}#dbase=no"


def tango_device_servers_args(prefix: str) -> list[str]:
    """Build the `-m ... <prefix>` argv for the fixed set of demo device servers.

    Doesn't start anything - pass the result to
    `ophyd_async.tango.testing.start_tango_device_servers` (which is where you
    can override which interpreter actually hosts the servers). There's no
    per-call configuration: every device this ends up serving has a name fixed
    by `predict_trl`.

    :param prefix: The domain/family prefix every served device's name is
        built from, e.g. via `ophyd_async.tango.testing.generate_random_trl_prefix()`.
    """
    return ["-m", "ophyd_async.tango.demo._tango_device_servers", prefix]


def _wire_demo_devices(prefix: str) -> None:
    """Connect the channel/detector devices to their motors/channels.

    Done here, once, so `tango_device_servers_args` is genuinely
    standalone-runnable with no external orchestration required.
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


def _serve(prefix: str) -> None:
    """Serve the Demo*Device classes, blocking until stdin closes."""
    from tango import GreenMode
    from tango.test_context import MultiDeviceTestContext

    from ._tango import (
        DemoMotorDevice,
        DemoMultiChannelDetectorDevice,
        DemoPointDetectorChannelDevice,
    )

    port = _port_for_prefix(prefix)
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
        _wire_demo_devices(prefix)
        print(_READY_MARKER, flush=True)
        sys.stdin.readline()  # block until our parent closes our stdin


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(f"Usage: {sys.argv[0]} <prefix>")
    _serve(sys.argv[1])
