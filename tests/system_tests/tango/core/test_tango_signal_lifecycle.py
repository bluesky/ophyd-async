"""Generic Signal-level lifecycle coverage for Tango, both device flavours.

Second slice of issue #1321 item 5 ("Tango wholesale Signal-level test
replacement"), extending the first slice (#1332, curated-declarative-only)
with two more pieces:

- An exhaustive procedural-device tier (`test_exhaustive_signal_lifecycle`):
  the same `assert_signal_lifecycle` helper as the curated tier below, but
  parametrized over *every* field `OneOfEverythingTangoDevice` serves (37,
  from `everything_signal_info`/`conftest.py`), via the plain procedural
  `TangoDevice(trl)` (default `auto_fill_signals=True`) rather than the
  curated declarative `TangoTestDevice`. Originally assumed too slow to be
  exhaustive (hence the first slice's curated 7-field subset) - measured
  instead of assumed: a prototype running the full lifecycle check
  (monitor+locate+describe, not just get/put) against all 37 fields took
  0.47s total. The curated declarative tier below stays curated regardless
  (that's a *different* constraint - mock-parity needs declared
  annotations, so it's inherently limited to whatever `TangoTestDevice`
  declares - not a coverage decision).
- A settings YAML round-trip test (`test_retrieve_apply_store_settings`),
  net-new for this transport, using the curated `TangoTestDevice` (settings
  save/apply is about a device's *declared* signal set, so curated is
  correct here, matching how EPICS's equivalent test uses its own
  declarative device).

`assert_signal_lifecycle` itself (below) is a single generic check run once
per field, replacing the large hand-curated per-field metadata table
`test_tango_signals.py` used (one `ExpectedData`-shaped entry per attribute)
- the same pattern already replicated for EPICS CA/PVA
(`tests/system_tests/epics/signal/test_epics_signal_lifecycle.py`).
`test_tango_signals.py` itself has now been deleted (issue #1321 item 5) -
see this PR's description for what was folded forward vs. dropped as
redundant.

Initial values/valid put values for each field are pulled from
`everything_signal_info` (`conftest.py`), and every test here resets
`OneOfEverythingTangoDevice` to its documented defaults first
(`reset_everything_device` fixture below), since it's a session-scoped
server shared with every other test module in this directory.

Performance note (CI regression fix, see PR discussion): two separate
costs were being paid once per parametrized case (44 cases combined,
`test_signal_lifecycle` + `test_exhaustive_signal_lifecycle`) instead of
once per module - `reset_everything_device`'s hardcoded `asyncio.sleep(1)`
(44 seconds of pure sleep alone), and a from-scratch `TangoDevice(...).
connect()` per case, which for the exhaustive tier's
`auto_fill_signals=True` means rediscovering all 37 attributes/commands on
every one of the 37 cases (see `TangoDeviceConnector.connect_real`).

`reset_everything_device` (below) is fixed by a plain per-process guard
flag: every case's own `assert_signal_lifecycle` already restores its
field to `initial` in a `finally`, so one real reset before the first case
in this module (to counter mutation by earlier-collected modules sharing
this session-scoped device) is all that's needed - repeating it bought
nothing.

`lifecycle_device`/`exhaustive_device` (below) fix the reconnect cost with
the same pattern EPICS's own system tests already use for this exact
scenario (`tests/system_tests/epics/signal/test_signals.py`'s
`ioc_devices` fixture + `assert_monitor_then_put`'s `await signal.connect
(timeout=1)`): construct the (unconnected) device *once*, in a plain
*synchronous* `scope="module"` fixture, then `await device.connect()`
inside each test as before. `Device.connect()` caches its result in an
`asyncio.Task` (`self._connect_task`, `src/ophyd_async/core/_device.py`) -
once that task is done, every later `.connect()` call just re-awaits the
same completed task, which is safe from a different test's event loop:
awaiting an already-done `asyncio.Task`/`Future` never touches the loop it
was created on (`Task.__await__` returns `self.result()` immediately
without yielding). So only the *first* parametrized case actually pays
the connect/discovery cost; the rest are cache hits. This avoids
pytest-asyncio's `loop_scope="module"` entirely (an earlier attempt using
it broke CI - see this PR's commit history for why), so it doesn't need
any change to the shared, function-scoped `event_loop` fixture in this
directory's `conftest.py`.
"""

import asyncio
from pathlib import Path
from typing import Annotated as A

import conftest
import numpy as np
import pytest
import tango
import yaml
from bluesky.protocols import Location
from tango.asyncio_executor import set_global_executor

from ophyd_async.core import (
    Array1D,
    DeviceVector,
    SignalRW,
    StandardReadable,
    YamlSettingsProvider,
)
from ophyd_async.plan_stubs import (
    apply_settings,
    ensure_connected,
    retrieve_settings,
    store_settings,
)
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


# Set the first time `reset_everything_device` actually does its (slow)
# work - see the fixture's own docstring for why this per-process guard
# exists instead of a module-scoped fixture.
_reset_everything_device_done = False


@pytest.fixture
async def reset_everything_device(everything_device_trl: str) -> None:
    """Force `OneOfEverythingTangoDevice` back to its documented defaults.

    Session-scoped server, shared with every other test module in this
    directory (some of which mutate it), so any test that wants a known
    starting value needs to force one first - same as
    `test_tango_signals.py::test_assert_val_reading_everything_tango` does.

    Guarded to only actually do that (a `connect()` plus a 1s settle sleep)
    once per test *process*, not once per request: every call site's own
    test (via `assert_signal_lifecycle`'s `finally`, or its own explicit
    restore) already leaves its field back at `initial` when it finishes,
    so a single reset before the first test in this module is sufficient -
    repeating the full connect+trigger+sleep(1) for all 44
    `test_signal_lifecycle`/`test_exhaustive_signal_lifecycle` parametrized
    cases was pure waste (measured directly in CI: ~44s of that 1s sleep
    alone). A plain per-process flag rather than `scope="module"`, unlike
    `lifecycle_device`/`exhaustive_device` below: those cache a *connect*,
    which is safe to reuse across tests/loops because awaiting an
    already-done `asyncio.Task` never touches its original loop (see their
    shared docstring). This fixture's own `asyncio.sleep(1)` is a genuinely
    new awaitable every call, not a cached-task replay, so the same trick
    doesn't apply here - a plain guard flag around the whole body is the
    direct equivalent.
    """
    global _reset_everything_device_done
    if _reset_everything_device_done:
        return
    resetter = TangoDevice(everything_device_trl, name="resetter")
    await resetter.connect()
    await resetter.reset_values.trigger()
    await asyncio.sleep(1)
    _reset_everything_device_done = True


@pytest.fixture(scope="module")
def lifecycle_device(everything_device_trl: str) -> TangoTestDevice:
    """Curated `TangoTestDevice`, constructed once and shared across every
    `test_signal_lifecycle` parametrized case (the 7 `LIFECYCLE_FIELDS`).

    Deliberately a plain *synchronous* fixture that only constructs the
    Device - it does not `connect()` it. Each test still calls `await
    device.connect()` itself (same as `exhaustive_device` below), which is
    what makes sharing this safe: `Device.connect()` caches its work in an
    `asyncio.Task` (`src/ophyd_async/core/_device.py`), so only the first
    test's call actually connects - every later call, even from a
    different test's event loop, just re-awaits that already-done task,
    which never touches the loop it was created on. This is the same
    pattern EPICS's own system tests already use for this exact scenario
    (`tests/system_tests/epics/signal/test_signals.py`'s `ioc_devices`
    fixture, constructed once and `.connect()`-ed per test/signal).
    """
    return TangoTestDevice(everything_device_trl, name="lifecycle")


@pytest.fixture(scope="module")
def exhaustive_device(everything_device_trl: str) -> TangoDevice:
    """Plain procedural `TangoDevice` (`auto_fill_signals=True`), constructed
    once and shared across every `test_exhaustive_signal_lifecycle`
    parametrized case (all 37 `EXHAUSTIVE_FIELDS`).

    See `lifecycle_device` above for why this is safe despite being shared
    across tests/event loops. `auto_fill_signals=True` discovers and
    connects *every* attribute/command on the device on first `connect()`
    (see `TangoDeviceConnector.connect_real`) - without this fixture, each
    of the 37 parametrized cases reconnecting its own fresh `TangoDevice`
    paid that whole-device discovery cost again, ~37x more network round
    trips than the single connect this module actually needs.
    """
    return TangoDevice(everything_device_trl, name="exhaustive")


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


def _distinct_put_value(attr_data: conftest.AttributeData, field: str):
    """A put value that's guaranteed to differ from `attr_data.initial`.

    `random_value()` picks from a small fixed choice list (e.g. 3 enum
    members) with no exclusion for "same as initial" - on a large enough
    test run that coincidence happens often enough to matter. A no-op set
    never fires a change event, so the monitor assertion inside
    `assert_signal_lifecycle` would hang until its own timeout instead of
    failing fast, rather than actually be wrong - so guarantee a genuine
    transition instead of trusting the coin flip.
    """
    put_value = attr_data.random_value()
    for _ in range(10):
        if not np.array_equal(put_value, attr_data.initial):
            return put_value
        put_value = attr_data.random_value()
    pytest.fail(f"Could not find a value for {field} that differs from initial")


@pytest.mark.timeout(10.0)
@pytest.mark.parametrize("field", LIFECYCLE_FIELDS)
async def test_signal_lifecycle(
    lifecycle_device: TangoTestDevice,
    everything_signal_info,
    reset_everything_device: None,
    field: str,
):
    # Cheap after the first call - see `lifecycle_device`'s docstring.
    await lifecycle_device.connect()
    signal = getattr(lifecycle_device, field)
    attr_data = everything_signal_info[field]
    initial_value = attr_data.initial
    put_value = _distinct_put_value(attr_data, field)
    await assert_signal_lifecycle(signal, initial_value, put_value)


# Every field OneOfEverythingTangoDevice serves (37), not just LIFECYCLE_FIELDS'
# curated 7 - built from the same plain function `everything_signal_info`
# itself wraps, since a `pytest.mark.parametrize` list has to exist at
# collection time, before any fixture (including `everything_signal_info`)
# has run. See `conftest.build_everything_signal_info`'s own docstring.
EXHAUSTIVE_FIELDS = sorted(conftest.build_everything_signal_info())


@pytest.mark.timeout(10.0)
@pytest.mark.parametrize("field", EXHAUSTIVE_FIELDS)
async def test_exhaustive_signal_lifecycle(
    exhaustive_device: TangoDevice,
    everything_signal_info,
    reset_everything_device: None,
    field: str,
):
    """Same lifecycle check as `test_signal_lifecycle` above, but exhaustive.

    Uses the plain procedural `TangoDevice(trl)` (`auto_fill_signals=True`)
    rather than `TangoTestDevice`, since a declarative Device would need a
    hand-written `Annotated` field for every one of the 37 fields to get
    this exhaustive - which the procedural flavour gets for free by
    discovering every attribute on the live proxy. See this module's
    docstring for why exhaustive coverage here is cheap enough to just do,
    rather than needing its own curated subset.
    """
    # Cheap after the first call - see `exhaustive_device`'s docstring.
    await exhaustive_device.connect()
    signal = getattr(exhaustive_device, field)
    # Confirmed empirically (see this module's docstring): every one of the
    # 37 fields discovered by auto_fill_signals=True comes back as a
    # SignalRW, since OneOfEverythingTangoDevice declares every attribute
    # READ_WRITE - so this never actually skips anything today. Kept as a
    # guard rather than assumed, the same way EPICS's lifecycle suite
    # documents its own quirk-field carve-outs, in case a future field is
    # ever added read-only.
    if not hasattr(signal, "set"):
        pytest.skip(f"{field} is not a settable Signal")
    attr_data = everything_signal_info[field]
    initial_value = attr_data.initial
    put_value = _distinct_put_value(attr_data, field)
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


@pytest.mark.timeout(5.0)
async def test_enum_set_accepts_name_value_and_member(
    everything_device_trl: str, reset_everything_device: None
):
    """An enum-backed `SignalRW.set()` accepts a raw string (the Tango-served
    label) or the enum member itself, not just one canonical form.

    Folded forward from the now-deleted `test_tango_signals.py::
    test_set_with_converter` - its `TypeError`/`ValueError` assertions were
    exact duplicates of `test_signal_error_paths` above (same field, same
    calls) so were dropped rather than folded forward; this is the
    genuinely distinct remainder. `LIFECYCLE_FIELDS`'/`EXHAUSTIVE_FIELDS`'
    `random_value()` only ever exercises the raw-string form (see
    `AttributeData.random_value` in conftest.py), never an actual enum
    member, so this converter-acceptance path has no other coverage.
    """
    device = TangoTestDevice(everything_device_trl, name="enum_converter")
    await device.connect()
    try:
        await device.strenum.set("AAA")
        await device.strenum.set(ExampleStrEnum.B)
        await device.strenum.set(ExampleStrEnum.C.value)
        await device.my_state.set(DevStateEnum.EXTRACT)
    finally:
        # Leave the server as documented-default for the next test/module.
        await device.strenum.set(ExampleStrEnum.B)
        await device.my_state.set(DevStateEnum.INIT)


HERE = Path(__file__).absolute().parent


@pytest.mark.timeout(10.0)
async def test_retrieve_apply_store_settings(
    RE, everything_device_trl: str, reset_everything_device: None, tmp_path
):
    """Settings YAML round-trip, net-new for Tango (issue #1321 item 5) -
    no equivalent existed under the old `test_tango_signals.py`. Follows the
    same shape as EPICS's `test_retrieve_apply_store_settings`
    (`tests/system_tests/epics/signal/test_signals.py`): retrieve a golden
    set of values from a YAML fixture, apply them to a real device, store
    the device's current values back out, and assert the two files agree.

    Uses the curated `TangoTestDevice`, not the exhaustive procedural tier
    above - `walk_rw_signals` (what `retrieve_settings`/`store_settings`
    walk) only ever sees a device's *declared* signals, so settings
    save/apply is inherently about the declarative flavour, the same way
    mock-parity is (see this module's docstring) - there's no equivalent
    "exhaustive" version of this test to write.
    """
    tmp_provider = YamlSettingsProvider(tmp_path)
    expected_provider = YamlSettingsProvider(HERE)
    device = TangoTestDevice(everything_device_trl, name="settings")

    # PyTango's asyncio green-mode machinery caches a single global executor
    # bound to whichever event loop first asks for one (see
    # tango.asyncio_executor.get_global_executor) - `reset_everything_device`
    # above already connected a device on *this* test's own (pytest-asyncio)
    # loop, which lazily bound that global executor here. `RE` runs its plan
    # on a second, separate event loop in its own background thread (see
    # tests/conftest.py's `RE` fixture) - without resetting, the first Tango
    # connect attempted from inside that thread reuses the wrong loop's
    # executor and fails with a raw `TypeError` ("... can't be used in
    # 'await' expression") instead of actually connecting. `reset_tango_asyncio`
    # (conftest.py, autouse) only resets once per test, before this happens -
    # doing it again immediately before handing off to `RE` is the same fix,
    # scoped to exactly the moment it's needed.
    set_global_executor(None)

    def a_plan():
        yield from ensure_connected(device)
        settings = yield from retrieve_settings(
            expected_provider, "test_yaml_save", device
        )
        yield from apply_settings(settings)
        yield from store_settings(tmp_provider, "test_file", device)
        with open(tmp_path / "test_file.yaml") as actual_file:
            with open(HERE / "test_yaml_save.yaml") as expected_file:
                # If this test fails because you added/removed a field on
                # TangoTestDevice, regenerate the golden file with:
                # cp /tmp/pytest-of-root/pytest-current/test_retrieve_apply_st0/test_file.yaml tests/system_tests/tango/core/test_yaml_save.yaml  # noqa: E501
                assert yaml.safe_load(actual_file) == yaml.safe_load(expected_file)

    RE(a_plan())
