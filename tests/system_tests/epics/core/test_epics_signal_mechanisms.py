"""EPICS-specific Signal/backend *mechanism* coverage - not datatype coverage.

Companion to `test_epics_signal_lifecycle.py`: when the old `test_signals.py`
(~1150 lines) was deleted as part of issue #1321 item 4, most of it turned
out to be a hand-curated per-field datatype table (now replaced by that
file's generic `assert_signal_lifecycle` sweep) - but a genuine remainder
wasn't datatype coverage at all, it was testing EPICS/`ophyd_async.epics`
*mechanisms*: precision/limits edge cases, direct-bit access, PV connection
error paths, `epics_signal_r/w/rw*` helper construction, put-completion,
retries, deprecation warnings, and a couple of PVI mechanics not subsumed by
the generic suite's own PVI dimension (see `test_pvi_wins_over_static_pv_suffix`/
`test_pvi_adds_undeclared_signal_dynamically` below for why those two
specifically still need their own test). None of this has a generic-helper
equivalent, so it's folded forward here verbatim (or near enough) rather than
silently dropped.
"""

import asyncio
import os
import re
import time
import typing
from enum import Enum
from typing import Any, Literal, get_args
from unittest.mock import patch

import bluesky.plan_stubs as bps
import numpy as np
import numpy.typing as npt
import pytest
from aioca import Subscription, purge_channel_caches
from bluesky.protocols import Location
from event_model import Limits, LimitsRange
from ophyd.signal import EpicsSignal

from ophyd_async.core import (
    Array1D,
    Command,
    NotConnectedError,
    Signal,
    SignalDatatypeT,
    SignalR,
    SignalRW,
    StrictEnum,
    SubsetEnum,
    observe_value,
    set_mock_value,
    soft_signal_r_and_setter,
)
from ophyd_async.epics.core import (
    CaCommandBackend,
    CaSignalBackend,
    PvaCommandBackend,
    PvaSignalBackend,
    epics_signal_r,
    epics_signal_rw,
    epics_signal_rw_rbv,
    epics_signal_w,
    epics_triggerable_command,
)

# format_datatype only renders a datatype for TypeError messages raised
# internally on a mismatch - a caller never calls it themselves, just sees
# its output inside an exception - checked, nothing here looks missing
# from the public interface.
from ophyd_async.epics.core._util import format_datatype  # noqa: PLC2701
from ophyd_async.epics.testing import (
    IOC,
    EpicsTestCaDevice,
    EpicsTestEnum,
    EpicsTestPvaDevice,
    EpicsTestPviDevice,
    generate_random_pv_prefix,
    start_ioc,
)
from ophyd_async.plan_stubs import ensure_connected
from ophyd_async.testing import MonitorQueue, assert_describe_signal

Protocol = Literal["ca", "pva"]

TIMEOUT = 30.0 if os.name == "nt" else 3.0

# Can be removed once numpy >=2 is pinned.
scalar_int_dtype = (
    "<i4" if os.name == "nt" and np.version.version.startswith("1.") else "<i8"
)


class MechanismIocAndDevices:
    """Devices/PVs for the mechanism tests in this module.

    A separate IOC process/prefix from `test_epics_signal_lifecycle.py`'s -
    each system test module in this directory starts and owns its own, same
    as that file and the old `test_signals.py` before it.
    """

    def __init__(self):
        self.prefix = generate_random_pv_prefix()
        ca_prefix = f"{self.prefix}ca:"
        pva_prefix = f"{self.prefix}pva:"
        self.ca_device = EpicsTestCaDevice(f"ca://{ca_prefix}")
        self.pva_device = EpicsTestPvaDevice(f"pva://{pva_prefix}")
        self.pvi_device = EpicsTestPviDevice(pva_prefix, with_pvi=True)

    def get_device(self, protocol: str) -> EpicsTestCaDevice | EpicsTestPvaDevice:
        return getattr(self, f"{protocol}_device")

    def get_signal(self, protocol: str, name: str) -> SignalRW:
        return getattr(self.get_device(protocol), name)

    def get_pv(self, protocol: str, name: str) -> str:
        return f"{protocol}://{self.prefix}{protocol}:{name}"


@pytest.fixture(scope="module")
def ioc_devices():
    ioc_devices = MechanismIocAndDevices()
    process = start_ioc(IOC, ioc_devices.prefix)
    yield ioc_devices
    # Purge the channel caches before we stop the IOC to stop
    # RuntimeError: Event loop is closed errors on teardown
    purge_channel_caches()
    process.stop()
    print(process.output)


async def assert_monitor_then_put(
    signal: SignalR[SignalDatatypeT],
    initial_value: SignalDatatypeT,
    put_value: SignalDatatypeT,
    metadata: dict,
):
    assert isinstance(signal, SignalRW)
    await signal.connect(timeout=1)
    with MonitorQueue(signal) as q:
        await q.assert_updates(initial_value)
        if isinstance(initial_value, np.ndarray):
            shape = list(initial_value.shape)
        else:
            shape = []
        await assert_describe_signal(signal, shape=shape, **metadata)
        await signal.set(put_value)
        await q.assert_updates(put_value)


# --- longstr/longstr2/bool_unnamed/float_prec_0: fields whose whole point is
# an EPICS-specific quirk (long-string encoding, an unnamed-choices bo record,
# 0-precision-as-int), not a "one more datatype" data point - kept as
# overrides on top of the generic sweep rather than folded into it.


class _Quirk:
    def __init__(self, initial, put, dtype, dtype_numpy, **metadata):
        self.initial = initial
        self.put = put
        self.metadata = dict(dtype=dtype, dtype_numpy=dtype_numpy, **metadata)


QUIRK_FIELDS: dict[str, _Quirk] = {
    "longstr": _Quirk(
        "a string that is just longer than forty characters",
        "another string that is just longer than forty characters",
        "string",
        "|S40",
    ),
    "longstr2": _Quirk(
        "a string that is just longer than forty characters",
        "another string that is just longer than forty characters",
        "string",
        "|S40",
    ),
    "bool_unnamed": _Quirk(True, False, "boolean", dtype_numpy="|b1"),
    "float_prec_0": _Quirk(3, 4, "integer", scalar_int_dtype, units="mm"),
    "partialint": _Quirk(
        42,
        43,
        "integer",
        scalar_int_dtype,
        limits=Limits(
            control=LimitsRange(low=10.0, high=90.0),
            alarm=LimitsRange(low=2.0, high=98.0),
            display=LimitsRange(low=0.0, high=100.0),
        ),
        units="",
    ),
    "lessint": _Quirk(
        42,
        43,
        "integer",
        scalar_int_dtype,
        limits=Limits(
            # control = display if DRVL, DRVH not set
            control=LimitsRange(low=0.0, high=100.0),
            # LOPR, HOPR
            display=LimitsRange(low=0.0, high=100.0),
            # LOW, HIGH
            warning=LimitsRange(low=2.0, high=98.0),
        ),
        units="",
    ),
}


@pytest.mark.timeout(TIMEOUT + 0.6)
@pytest.mark.parametrize("protocol", get_args(Protocol))
@pytest.mark.parametrize("name,data", list(QUIRK_FIELDS.items()))
async def test_epics_quirk_fields_get_put_monitor(
    ioc_devices: MechanismIocAndDevices, protocol: Protocol, name: str, data: _Quirk
):
    signal = ioc_devices.get_signal(protocol, name)
    await assert_monitor_then_put(signal, data.initial, data.put, data.metadata)
    # Put back, proving the round trip works in both directions.
    await assert_monitor_then_put(signal, data.put, data.initial, data.metadata)


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_mbb_direct_bit_access(
    ioc_devices: MechanismIocAndDevices, protocol: Protocol
):
    """`.B0` field suffix syntax reads/writes a single bit of an
    mbbiDirect/mbboDirect record directly, decoded as bool -
    `mbb_direct_bit_r`/`mbb_direct_bit` exercise the read-only and
    read-write sides of this respectively (different underlying records,
    not a read/readback pair of the same one)."""
    device = ioc_devices.get_device(protocol)
    await device.mbb_direct_bit_r.connect()
    await device.mbb_direct_bit.connect()
    assert isinstance(await device.mbb_direct_bit_r.get_value(), bool)

    initial = await device.mbb_direct_bit.get_value()
    assert isinstance(initial, bool)
    await device.mbb_direct_bit.set(not initial)
    assert await device.mbb_direct_bit.get_value() is (not initial)
    await device.mbb_direct_bit.set(initial)


@pytest.mark.timeout(TIMEOUT)
async def test_invalid_enum_choice_raises_valueerror(
    ioc_devices: MechanismIocAndDevices,
):
    """enum_str_fallback exercises the fallback-to-str path for an mbb
    record with no declared StrictEnum/SubsetEnum - invalid choices still
    raise ValueError, with a message naming both the PV and valid choices."""
    signal = ioc_devices.ca_device.enum_str_fallback
    await signal.connect()
    with pytest.raises(ValueError) as exc:
        await signal.set("Ddd")
    assert "Ddd is not a valid choice for" in str(exc.value)
    assert "ca:enum_str_fallback, valid choices: ['Aaa', 'Bbb', 'Ccc']" in str(
        exc.value
    )


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_typing_sequence_str_signal_connects(
    ioc_devices: MechanismIocAndDevices, protocol: Protocol
):
    # Explicitly test that we can connect to a typing.Sequence[str] signal
    # rather than a collections.abc.Sequence[str] which is more normal
    signal = epics_signal_rw(typing.Sequence[str], ioc_devices.get_pv(protocol, "stra"))
    await signal.connect()


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_error_raised_on_disconnected_pv(
    ioc_devices: MechanismIocAndDevices, protocol: Protocol
):
    signal = epics_signal_rw(bool, ioc_devices.get_pv(protocol, "bool"))
    await signal.connect()
    # The below will work without error
    await signal.set(False)
    # Override the PV so it fails
    signal._connector.backend.write_pv = "DisconnectedPv"  # type: ignore
    with pytest.raises(asyncio.TimeoutError, match=f"{protocol}://DisconnectedPv"):
        await signal.set(True, timeout=0.1)


class BadEnum(StrictEnum):
    A = "Aaa"
    B = "B"
    C = "Ccc"


class EnumNoString(Enum):
    A = "Aaa"


class SubsetEnumWrongChoices(SubsetEnum):
    A = "Aaa"
    B = "B"
    C = "Ccc"


def test_enum_equality():
    """Check that we are allowed to replace the passed datatype enum from a signal with
    a version generated from the signal with at least all of the same values, but
    possibly more.
    """

    class GeneratedChoices(StrictEnum):
        A = "Aaa"
        B = "B"
        C = "Ccc"

    class ExtendedGeneratedChoices(StrictEnum):
        A = "Aaa"
        B = "B"
        C = "Ccc"
        D = "Ddd"

    for enum_class in (GeneratedChoices, ExtendedGeneratedChoices):
        assert BadEnum.A == enum_class.A
        assert BadEnum.A.value == enum_class.A
        assert BadEnum.A.value == enum_class.A.value
        assert BadEnum(enum_class.A) is BadEnum.A
        assert BadEnum(enum_class.A.value) is BadEnum.A
        assert not BadEnum == enum_class

    # We will always PUT BadEnum by String, and GET GeneratedChoices by index,
    # so shouldn't ever run across this from conversion code, but may occur if
    # casting returned values or passing as enum rather than value.
    with pytest.raises(ValueError):
        BadEnum(ExtendedGeneratedChoices.D)


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
@pytest.mark.parametrize(
    "typ, suff, errors",
    [
        (
            BadEnum,
            "enum",
            (
                "has choices ('Aaa', 'Bbb', 'Ccc')",
                "but <enum 'BadEnum'>",
                "requested ['Aaa', 'B', 'Ccc'] to be strictly equal",
            ),
        ),
        (
            SubsetEnumWrongChoices,
            "enum",
            (
                "has choices ('Aaa', 'Bbb', 'Ccc')",
                "but <enum 'SubsetEnumWrongChoices'>",
                "requested ['Aaa', 'B', 'Ccc'] to be a subset",
            ),
        ),
        (
            int,
            "str",
            ("with inferred datatype str", "cannot be coerced to int"),
        ),
        (
            str,
            "float",
            ("with inferred datatype float", "cannot be coerced to str"),
        ),
        (
            str,
            "stra",
            ("with inferred datatype Sequence[str]", "cannot be coerced to str"),
        ),
        (
            int,
            "uint8a",
            ("with inferred datatype Array1D[np.uint8]", "cannot be coerced to int"),
        ),
        (
            float,
            "enum",
            ("with inferred datatype str", "cannot be coerced to float"),
        ),
        (
            Array1D[np.int32],
            "float64a",
            (
                "with inferred datatype Array1D[np.float64]",
                "cannot be coerced to Array1D[np.int32]",
            ),
        ),
        (
            EnumNoString,
            "enum2",
            (
                "<enum 'EnumNoString'> should inherit from ",
                "ophyd_async.core.SubsetEnum or ophyd_async.core.StrictEnum",
            ),
        ),
    ],
)
async def test_backend_wrong_type_errors(
    ioc_devices: MechanismIocAndDevices, typ, suff, errors, protocol: Protocol
):
    signal = epics_signal_rw(typ, ioc_devices.get_pv(protocol, suff))
    with pytest.raises(TypeError) as exc:
        await signal.connect()
    for error in errors:
        assert error in str(exc.value)


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_backend_put_enum_string(
    ioc_devices: MechanismIocAndDevices, protocol: Protocol
):
    signal = ioc_devices.get_signal(protocol, "enum2")
    await signal.connect()
    await signal.set("Ccc")
    assert (
        Location(setpoint=EpicsTestEnum.C, readback=EpicsTestEnum.C)
        == await signal.locate()
    )
    val = await signal.get_value()
    assert val == "Ccc"
    assert val is EpicsTestEnum.C
    assert repr(val) == "<EpicsTestEnum.C: 'Ccc'>"


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_non_existent_errors(
    ioc_devices: MechanismIocAndDevices, protocol: Protocol
):
    signal = epics_signal_rw(str, "non-existent")
    with pytest.raises(NotConnectedError):
        await signal.connect(timeout=0.1)


@pytest.mark.parametrize(
    "dt,expected",
    [
        (Array1D[np.int32], "Array1D[np.int32]"),
        (np.ndarray, "ndarray"),
        (npt.NDArray[np.float64], "Array1D[np.float64]"),
    ],
)
def test_format_error_message(dt, expected):
    assert format_datatype(dt) == expected


def test_make_backend_fails_for_different_transports():
    read_pv = "test"
    write_pv = "pva://test"

    with pytest.raises(
        TypeError,
        match=f"Differing protocols: {read_pv} has EpicsProtocol.CA,"
        + f" {write_pv} has EpicsProtocol.PVA",
    ):
        epics_signal_rw(str, read_pv, write_pv)


def _get_epics_backend(signal: Signal) -> CaSignalBackend | PvaSignalBackend:
    backend = signal._connector.backend
    assert isinstance(backend, CaSignalBackend | PvaSignalBackend)
    return backend


def _get_command_backend(command: Command) -> CaCommandBackend | PvaCommandBackend:
    backend = command._connector.backend
    assert isinstance(backend, CaCommandBackend | PvaCommandBackend)
    return backend


def test_signal_helpers():
    read_write = epics_signal_rw(int, "ReadWrite")
    assert _get_epics_backend(read_write).read_pv == "ReadWrite"
    assert _get_epics_backend(read_write).write_pv == "ReadWrite"

    read_write_rbv_manual = epics_signal_rw(int, "ReadWrite_RBV", "ReadWrite")
    assert _get_epics_backend(read_write_rbv_manual).read_pv == "ReadWrite_RBV"
    assert _get_epics_backend(read_write_rbv_manual).write_pv == "ReadWrite"

    read_write_rbv = epics_signal_rw_rbv(int, "ReadWrite")
    assert _get_epics_backend(read_write_rbv).read_pv == "ReadWrite_RBV"
    assert _get_epics_backend(read_write_rbv).write_pv == "ReadWrite"

    read_write_rbv_suffix = epics_signal_rw_rbv(int, "ReadWrite", read_suffix=":RBV")
    assert _get_epics_backend(read_write_rbv_suffix).read_pv == "ReadWrite:RBV"
    assert _get_epics_backend(read_write_rbv_suffix).write_pv == "ReadWrite"

    read_write_rbv_w_field = epics_signal_rw_rbv(int, "ReadWrite.VAL")
    assert _get_epics_backend(read_write_rbv_w_field).read_pv == "ReadWrite_RBV.VAL"
    assert _get_epics_backend(read_write_rbv_w_field).write_pv == "ReadWrite.VAL"

    read = epics_signal_r(int, "Read")
    assert _get_epics_backend(read).read_pv == "Read"

    write = epics_signal_w(int, "Write")
    assert _get_epics_backend(write).write_pv == "Write"

    execute = epics_triggerable_command("Execute")
    assert _get_command_backend(execute).write_pv == "Execute"


def test_signal_helpers_explicit_read_timeout():
    # Check that we can adjust the _timeout attribute, which is used
    # for example during await signal.get_value()

    read_write = epics_signal_rw(int, "ReadWrite", timeout=123)
    assert read_write._timeout == 123

    read_write_rbv = epics_signal_rw_rbv(int, "ReadWrite", timeout=456)
    assert read_write_rbv._timeout == 456

    read = epics_signal_r(int, "Read", timeout=789)
    assert read._timeout == 789

    write = epics_signal_w(int, "Write", timeout=987)
    assert write._timeout == 987

    execute = epics_triggerable_command("Execute", timeout=654)
    assert execute._timeout == 654


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_signals_created_for_not_prec_0_float_cannot_use_int(
    ioc_devices: MechanismIocAndDevices, protocol: Protocol
):
    sig = epics_signal_rw(int, ioc_devices.get_pv(protocol, "float_prec_1"))
    with pytest.raises(
        TypeError,
        match="float_prec_1 with inferred datatype float.* cannot be coerced to int",
    ):
        await sig.connect()


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_bool_works_for_mismatching_enums(
    ioc_devices: MechanismIocAndDevices, protocol: Protocol
):
    pv_name = ioc_devices.get_pv(protocol, "bool")
    sig = epics_signal_rw(bool, pv_name, pv_name + "_unnamed")
    await sig.connect()


@pytest.mark.timeout(TIMEOUT)
async def test_can_read_using_ophyd_async_then_ophyd(
    RE, ioc_devices: MechanismIocAndDevices
):
    ophyd_async_sig = epics_signal_rw(float, ioc_devices.get_pv("ca", "float_prec_1"))
    await ophyd_async_sig.connect()
    ophyd_signal = EpicsSignal(ioc_devices.get_pv("ca", "float_prec_0").split("://")[1])
    ophyd_signal.wait_for_connection(timeout=5)

    def a_plan():
        yield from bps.rd(ophyd_async_sig)
        yield from bps.rd(ophyd_signal)

    RE(a_plan())


def test_signal_module_emits_deprecation_warning():
    with pytest.deprecated_call():
        import ophyd_async.epics.signal  # noqa: F401


@pytest.mark.timeout(TIMEOUT + 0.6)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_observe_ticking_signal_with_busy_loop(
    ioc_devices: MechanismIocAndDevices, protocol: Protocol
):
    sig = epics_signal_rw(int, ioc_devices.get_pv("ca", "ticking"))
    await sig.connect()

    recv = []

    async def watch():
        async for val in observe_value(sig, done_timeout=0.4):
            time.sleep(0.3)
            recv.append(val)

    start = time.monotonic()

    with pytest.raises(asyncio.TimeoutError):
        await watch()
    assert time.monotonic() - start == pytest.approx(0.6, abs=0.1)
    assert len(recv) == 2
    # Don't check values as CA and PVA have different algorithms for
    # dropping updates for slow callbacks


@pytest.mark.parametrize(
    "all_updates,expected_all_updates",
    [("True", True), ("False", False)],
)
@pytest.mark.timeout(TIMEOUT + 0.6)
async def test_all_updates_settable_with_environment_variable(
    ioc_devices: MechanismIocAndDevices,
    all_updates: Any,
    expected_all_updates: bool,
):
    with patch.dict(
        os.environ,
        {**os.environ, "OPHYD_ASYNC_EPICS_CA_KEEP_ALL_UPDATES": all_updates},
        clear=True,
    ):
        assert (
            await default_all_updates(ioc_devices.get_pv("ca", "ticking"))
        ) is expected_all_updates


@pytest.mark.timeout(TIMEOUT + 0.6)
async def test_all_updates_defaults_to_true(
    ioc_devices: MechanismIocAndDevices,
):
    assert await default_all_updates(ioc_devices.get_pv("ca", "ticking"))


async def default_all_updates(pv: str) -> bool:
    sig = epics_signal_rw(int, pv)
    await sig.connect()
    backend = sig._connector.backend

    try:
        sig.subscribe_reading(lambda v: ...)
        assert isinstance(backend.subscription, Subscription)
        assert isinstance(backend.subscription.all_updates, bool)
        return backend.subscription.all_updates
    finally:
        backend.subscription.close()
        sig.clear_sub(lambda v: ...)


@pytest.mark.timeout(TIMEOUT + 0.5)
@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_put_completion(
    RE, ioc_devices: MechanismIocAndDevices, protocol: Protocol
):
    # Check that we can put to an epics signal and wait for put completion
    slow_seq_pv = ioc_devices.get_pv(protocol, "slowseq")
    slow_seq = epics_signal_rw(int, slow_seq_pv, wait=lambda value: value == 1)
    await slow_seq.connect()

    # First, do a set with blocking and make sure it takes a while
    start = time.monotonic()
    await slow_seq.set(1)
    stop = time.monotonic()
    assert stop - start == pytest.approx(0.5, rel=0.1)

    # Then, make sure if we don't wait it returns ~instantly
    start = time.monotonic()
    await slow_seq.set(2)
    stop = time.monotonic()
    assert stop - start < 0.1

    # Time for completion callback to have finished before moving to
    # next test / iteration - without this, running this test multiple
    # times in a row will fail even-numbered runs.
    await asyncio.sleep(0.5)


@pytest.mark.timeout(TIMEOUT + 0.5)
async def test_setting_with_none_uses_initial_value_of_pv(
    ioc_devices: MechanismIocAndDevices,
):
    sig_rw = epics_signal_rw(int, ioc_devices.get_pv("pva", "slowseq"))
    await sig_rw.connect()
    initial_data = await sig_rw.read()
    initial_value, initial_timestamp = (
        initial_data[""]["value"],
        initial_data[""]["timestamp"],
    )

    # This mimics triggering a SignalX
    await sig_rw.set(None)  # type: ignore

    current_data = await sig_rw.read()
    assert (
        initial_value == current_data[""]["value"]
        and initial_timestamp != current_data[""]["timestamp"]
    )


@pytest.mark.timeout(TIMEOUT + 0.5)
async def test_signal_retries_when_timeout(
    ioc_devices: MechanismIocAndDevices,
):
    # put callback on slowseq in 0.5s, so if waited, this will fail to set
    sig_rw_times_out = epics_signal_rw(
        int, ioc_devices.get_pv("pva", "slowseq"), attempts=3, timeout=0.1
    )
    await sig_rw_times_out.connect()

    start = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        await sig_rw_times_out.set(1)
    stop = time.monotonic()
    # signal tries to set 3 times, so 3 * timeout
    assert stop - start == pytest.approx(0.3, abs=0.1)


async def test_signal_timestamp_is_same_format_as_soft_signal_timestamp(
    RE, ioc_devices: MechanismIocAndDevices
):
    sim_sig, sim_sig_setter = soft_signal_r_and_setter(float)
    real_sig = epics_signal_rw(float, ioc_devices.get_pv("ca", "float_prec_1"))
    await real_sig.connect(timeout=30)

    await real_sig.set(10)
    sim_sig_setter(20)

    real_data = await real_sig.read()
    sim_data = await sim_sig.read()

    assert abs(real_data[""]["timestamp"] - sim_data[""]["timestamp"]) < 0.1


@pytest.mark.parametrize("protocol", get_args(Protocol))
@pytest.mark.parametrize("mock", [True, False])
def test_subscribe_works_under_re_and_fails_outside(
    RE, ioc_devices: MechanismIocAndDevices, protocol: Protocol, mock: bool
):
    s1 = epics_signal_r(float, ioc_devices.get_pv(protocol, "float"), "s1")
    s2 = epics_signal_r(float, ioc_devices.get_pv(protocol, "float"), "s2")

    # Run in the RE event loop
    def plan():
        yield from ensure_connected(s1, s2, mock=mock)
        if mock:
            set_mock_value(s1, 3.141)
        q = asyncio.Queue()
        s1.subscribe_reading(q.put_nowait)
        try:
            (fut,) = yield from bps.wait_for([q.get])
            assert fut.result()["s1"]["value"] == 3.141
        finally:
            s1.clear_sub(q.put_nowait)

    RE(plan())

    # Run plan outside RE and outside event loop
    with pytest.raises(
        RuntimeError,
        match="Need a running event loop to subscribe to a signal, "
        "are you trying to run subscribe outside a plan?",
    ):
        s2.subscribe_reading(print)


@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_command_backends_accept_enum(
    ioc_devices: MechanismIocAndDevices, protocol
):
    triggerable_enum = epics_triggerable_command(ioc_devices.get_pv(protocol, "enum"))
    await triggerable_enum.connect()


@pytest.mark.parametrize("protocol", get_args(Protocol))
async def test_command_backends_raise_with_float(
    ioc_devices: MechanismIocAndDevices, protocol
):
    triggerable_float = epics_triggerable_command(
        ioc_devices.get_pv(protocol, "float_prec_1")
    )
    with pytest.raises(TypeError, match=re.escape("requires a scalar numeric PV")):
        await triggerable_float.connect()


# --- PVI mechanics not subsumed by test_epics_signal_lifecycle.py's own PVI
# dimension. That file's `pvi=True` cases connect EpicsTestCaDevice/
# EpicsTestPvaDevice - the same static Devices as their non-PVI cases - via
# PVI discovery instead, proving the datatype coverage carries over. These
# two check PVI-*specific* mechanics with no non-PVI equivalent to piggyback
# on, so they still need EpicsTestPviDevice directly. The old file's other
# PVI-specific tests (test_pvi_scalar_signal_kinds, test_pvi_table,
# test_pvi_ntndarray, test_pvi_command) are genuinely subsumed - the r/w/rw
# signal kinds, table, ntndarray and go command they checked are now all
# exercised through the pvi=True dimension in test_epics_signal_lifecycle.py.


@pytest.fixture
async def pvi_device(ioc_devices: MechanismIocAndDevices) -> EpicsTestPviDevice:
    await ioc_devices.pvi_device.connect(timeout=TIMEOUT)
    return ioc_devices.pvi_device


async def test_pvi_wins_over_static_pv_suffix(pvi_device: EpicsTestPviDevice):
    # overridden_float carries PvSuffix("float_prec_1"), but the real PVI
    # directory points it at the same record as a_float: the PVI-supplied
    # PV should win once connected.
    await pvi_device.a_float.set(4.5)
    assert await pvi_device.overridden_float.get_value() == 4.5


async def test_pvi_adds_undeclared_signal_dynamically(pvi_device: EpicsTestPviDevice):
    # extra_int has a PVI entry but is not an annotation on EpicsTestPviDevice
    assert "extra_int" not in EpicsTestPviDevice.__annotations__
    extra_int = pvi_device.extra_int  # type: ignore[attr-defined]
    assert isinstance(extra_int, SignalRW)
    assert await extra_int.get_value() == 42
