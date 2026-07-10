"""Generic Signal-level lifecycle coverage for the declarative `TangoTestDevice`.

First slice of issue #1321 item 4 ("New Signal-level system test suites
(get/put/monitor/describe/locate/mock-parity/error-paths) per transport,
replacing the old ones"): rather than a large hand-curated per-field metadata
table like `test_tango_signals.py` uses (one `ExpectedData`-shaped entry per
attribute, repeated per transport), `assert_signal_lifecycle` below is a
single generic check run once per field, parametrized over
`TangoTestDevice`'s own curated field list (built in item 3) - the same
pattern is intended to be replicated for EPICS CA/PVA/PVI and `core` in
follow-up PRs, and for the "old" `test_tango_signals.py` to eventually be
deleted in favour of it (issue #1321 item 6).

Initial values/valid put values for each field are pulled from
`everything_signal_info` (`conftest.py`), same as `test_tango_signals.py` -
and like that module, every test here resets `OneOfEverythingTangoDevice` to
its documented defaults first (`reset_everything_device` fixture below),
since it's a session-scoped server shared with every other test module in
this directory.
"""

import asyncio
from typing import Annotated as A

import numpy as np
import pytest
import tango
from bluesky.protocols import Location

from ophyd_async.core import Array1D, DeviceVector, SignalRW, StandardReadable
from ophyd_async.tango.core import DevStateEnum, TangoDevice, TangoPolling
from ophyd_async.tango.testing import ExampleStrEnum, TangoTestDevice
from ophyd_async.testing import MonitorQueue, approx_value

# Fields common to every category below (get/put/monitor/describe/locate) -
# the full curated set `TangoTestDevice` declares, per its own docstring.
LIFECYCLE_FIELDS = [
    "a_str",
    "a_bool",
    "strenum",
    "my_state",
    "float64",
    "int32_spectrum",
    "float64_image",
]


class _MockableTestDevice(TangoDevice, StandardReadable):
    """`TangoTestDevice`, minus `float64_image`, for the mock-parity test below.

    `float64_image` is annotated `np.ndarray[Any, np.dtype[np.float64]]` on
    the real `TangoTestDevice` - needed so the *real* connector's
    dtype-matching accepts it (see `TangoTestDevice`'s own docstring: real
    image attributes need a dtype-narrowed annotation to pass
    `_verify_datatype_matches`, confirmed by trying the obvious fix of
    switching it to bare `np.ndarray` - that breaks real `connect()`
    instead). But `SoftSignalBackend.make_converter` only accepts bare
    `np.ndarray` or an `Array1D[dtype]` (1-D, shape `tuple[int, ...]`) for
    mock/soft signals, not that "any-shape, fixed-dtype" spelling, so
    `TangoTestDevice.connect(mock=True)` raises `TypeError: Expected
    Array1D[dtype], got numpy.ndarray[typing.Any, numpy.dtype[numpy.float64]]`
    - for the *whole device*, since `connect(mock=True)` mock-fills every
    declared field, not just the one that was asked for. Every other
    image-typed signal in this codebase is annotated bare `np.ndarray` (e.g.
    `EpicsTestPvaDevice.ntndarray`), which doesn't hit this -
    `TangoTestDevice.float64_image` looks to be the only dtype-narrowed one.
    Not fixed at the `core` level here (mock-mode support for "any-shape,
    fixed-dtype" ndarrays is a `SignalDatatype`/`SoftSignalBackend` change,
    out of scope for this slice) - see #1335; this local subclass sidesteps
    it so the other 6 fields still get real mock-parity coverage.
    """

    a_str: A[SignalRW[str], TangoPolling(0.1)]
    a_bool: A[SignalRW[bool], TangoPolling(0.1)]
    strenum: A[SignalRW[ExampleStrEnum], TangoPolling(0.1)]
    my_state: A[SignalRW[DevStateEnum], TangoPolling(0.1)]
    float64: A[SignalRW[float], TangoPolling(0.1, 0.001, 0.001)]
    int32_spectrum: A[SignalRW[Array1D[np.int_]], TangoPolling(0.1)]

    def __init__(self, trl: str = "", name: str = "") -> None:
        super().__init__(trl, name=name, auto_fill_signals=False)


MOCK_PARITY_FIELDS = [f for f in LIFECYCLE_FIELDS if f != "float64_image"]


@pytest.fixture
async def reset_everything_device(everything_device_trl: str) -> None:
    """Force `OneOfEverythingTangoDevice` back to its documented defaults.

    Session-scoped server, shared with every other test module in this
    directory (some of which mutate it), so any test that wants a known
    starting value needs to force one first - same as
    `test_tango_signals.py::test_assert_val_reading_everything_tango` does.
    """
    resetter = TangoDevice(everything_device_trl, name="resetter")
    await resetter.connect()
    await resetter.reset_values.trigger()
    await asyncio.sleep(1)


async def assert_signal_lifecycle(signal: SignalRW, initial_value, put_value) -> None:
    """Exercise get/put/monitor/describe/locate on an already-connected signal."""
    describe_before = await signal.describe()

    try:
        with MonitorQueue(signal) as q:
            # get + monitor: initial value arrives on subscribe
            await q.assert_updates(initial_value)

            # locate (readback half only): Tango's own write-value cache
            # (what `locate`'s "setpoint" reads, via `get_w_value()`) is
            # whatever was last *actually written* through the Tango
            # protocol since this device server process started - which,
            # for a signal this test session's client hasn't `set()` yet,
            # is a cppTango-level placeholder unrelated to `reset_values`
            # (a custom command that only rewrites this server's own
            # `read()`/`fget` dict, not cppTango's write-value cache). Not
            # meaningful to assert against until after the `set()` below.
            location: Location = await signal.locate()
            assert approx_value(initial_value) == location["readback"]

            # put + monitor: new value arrives after set()
            await signal.set(put_value)
            await q.assert_updates(put_value)

        # locate again: setpoint and readback have moved to the new value
        location = await signal.locate()
        assert approx_value(put_value) == location["setpoint"]
        assert approx_value(put_value) == location["readback"]

        # describe: dtype/shape is stable across the whole lifecycle - a put
        # never changes what a signal *is*, only its value
        describe_after = await signal.describe()
        assert describe_before == describe_after
    finally:
        # Leave the server exactly as we found it for the next test/module
        # sharing this session-scoped device.
        await signal.set(initial_value)


@pytest.mark.timeout(10.0)
@pytest.mark.parametrize("field", LIFECYCLE_FIELDS)
async def test_signal_lifecycle(
    everything_device_trl: str,
    everything_signal_info,
    reset_everything_device: None,
    field: str,
):
    device = TangoTestDevice(everything_device_trl, name="lifecycle")
    await device.connect()
    signal = getattr(device, field)
    attr_data = everything_signal_info[field]
    initial_value = attr_data.initial
    # random_value() picks from a small fixed choice list (e.g. 3 enum
    # members) with no exclusion for "same as initial" - on a large enough
    # test run that coincidence happens often enough to matter. A no-op set
    # never fires a change event, so the monitor assertion inside
    # `assert_signal_lifecycle` would hang until its own timeout instead of
    # failing fast, rather than actually be wrong - so guarantee a genuine
    # transition instead of trusting the coin flip.
    put_value = attr_data.random_value()
    for _ in range(10):
        if not np.array_equal(put_value, initial_value):
            break
        put_value = attr_data.random_value()
    else:
        pytest.fail(f"Could not find a value for {field} that differs from initial")
    await assert_signal_lifecycle(signal, initial_value, put_value)


@pytest.mark.timeout(10.0)
async def test_signal_mock_parity(
    everything_device_trl: str, reset_everything_device: None
):
    """A mock-connected device agrees on shape/dtype with a real-connected
    one, and never touches the network for get/set. See `_MockableTestDevice`
    for why this uses that rather than the real `TangoTestDevice`."""
    real = _MockableTestDevice(everything_device_trl, name="real")
    # Never dialled: mock mode skips connect_real entirely.
    mock = _MockableTestDevice("does/not/matter#dbase=no", name="mock")
    await real.connect()
    await mock.connect(mock=True)

    for field in MOCK_PARITY_FIELDS:
        real_signal = getattr(real, field)
        mock_signal = getattr(mock, field)

        real_datakey = (await real_signal.describe())[real_signal.name]
        mock_datakey = (await mock_signal.describe())[mock_signal.name]
        # dtype (the logical category - "integer"/"array"/...) matches, but
        # dtype_numpy (precise wire format) legitimately doesn't always:
        # `int32_spectrum` is annotated `Array1D[np.int_]` (platform-native
        # width - see `TangoTestDevice`'s own docstring for why), so the
        # mock signal's dtype_numpy reflects `np.int_` (`<i8` on this
        # platform), while the real signal's reflects what the *server*
        # actually declared for `DevLong` (`<i4`) - a real, inherent
        # consequence of Tango mapping every signed int width to plain
        # `int`, not a bug to paper over here.
        assert real_datakey["dtype"] == mock_datakey["dtype"]

        # A value that's valid for the real signal is valid for its mock
        # twin, and setting it never reaches the real device.
        put_value = await real_signal.get_value()
        await mock_signal.set(put_value)
        assert approx_value(put_value) == await mock_signal.get_value()


class _DeviceVectorTestDevice(TangoDevice, StandardReadable):
    """Minimal declarative Device with a `DeviceVector` field.

    Neither `TangoTestDevice` nor `OneOfEverythingTangoDevice` (the real
    server it pairs with) declares a `DeviceVector` field, so mock-connecting
    the real curated device never exercises
    `TangoDeviceConnector.connect_mock`'s `isinstance(device, DeviceVector)`
    branch (added on this same PR to fix a bug where it unconditionally
    called `create_device_vector_entries_to_mock` for *every* device, vector
    or not). This one-off Device exists purely to mock-connect and exercise
    that branch - it's never connected for real, so `items` isn't backed by
    any actual Tango attribute.
    """

    items: DeviceVector[SignalRW[int]]

    def __init__(self, name: str = "") -> None:
        super().__init__(name=name, auto_fill_signals=False)


@pytest.mark.timeout(5.0)
async def test_device_vector_mock_connect():
    """`connect(mock=True)` fills a `DeviceVector` field with mock entries.

    See `_DeviceVectorTestDevice`'s docstring for why this needs its own
    throwaway Device rather than reusing `TangoTestDevice`.
    """
    device = _DeviceVectorTestDevice(name="vector")
    await device.connect(mock=True)

    assert set(device.items) == {1, 2}
    for signal in device.items.values():
        assert isinstance(signal, SignalRW)

    # Each entry behaves like any other mock signal - settable, gettable,
    # never touching the network.
    await device.items[1].set(5)
    assert await device.items[1].get_value() == 5


@pytest.mark.timeout(5.0)
async def test_signal_error_paths(everything_device_trl: str):
    device = TangoTestDevice(everything_device_trl, name="errors")
    await device.connect()

    # Wrong Python type for a StrictEnum signal
    with pytest.raises(TypeError):
        await device.strenum.set(0)

    # Right type, not a valid choice
    with pytest.raises(ValueError):
        await device.strenum.set("NOT_A_REAL_CHOICE")

    # A well-formed TRL (real host:port, so PyTango accepts the syntax) but
    # for a device name nothing is serving. Unlike a bad *attribute* TRL
    # (wrapped into `NotConnectedError` by `wait_for_connection`, since it
    # fails once inside the per-child dispatch in `connect_real`), a bad
    # *device* TRL fails one statement earlier - the `AsyncDeviceProxy(trl)`
    # call at the very top of `TangoDeviceConnector.connect_real`, before
    # there's any child to dispatch through - so it's genuinely unwrapped
    # today: a raw `tango.DevFailed`, not `NotConnectedError`. EPICS has no
    # equivalent "whole-device proxy" connect step so doesn't share this gap
    # (`test_signals.py::test_non_existent_errors` reliably gets
    # `NotConnectedError` for a bad PV). See #1336; asserting the actual
    # current behaviour here rather than the behaviour this slice would
    # like it to have - update this to `pytest.raises(NotConnectedError)`
    # once that's fixed.
    missing_trl = everything_device_trl.rsplit("/", 1)[0] + "/no-such-device#dbase=no"
    missing = TangoTestDevice(missing_trl, name="missing")
    with pytest.raises(tango.DevFailed):
        await missing.connect(timeout=0.5)
