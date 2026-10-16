"""Generic Signal-level lifecycle coverage for EpicsTestCaDevice/EpicsTestPvaDevice.

Item 4 of issue #1321 ("New Signal-level system test suites (get/put/monitor/
describe/locate/mock-parity/error-paths) per transport, replacing the old
ones"), following the pattern established for Tango by
`tests/system_tests_tango/test_tango_signal_lifecycle.py` (see its module
docstring for the full rationale): rather than a large hand-curated per-field
metadata table like the old `test_signals.py` used (one `ExpectedData`-shaped
entry per attribute, repeated per transport), `assert_signal_lifecycle` below
is a single generic check run once per field.

Unlike the Tango suite, coverage here is genuinely exhaustive, not curated:
`EpicsTestCaDevice`/`EpicsTestPvaDevice` already declare every in-scope
datatype with no procedural/declarative split to exploit (see their own
docstrings), so there's no technical reason to sample rather than iterate
everything. This was originally assumed to be too slow to do exhaustively
(a holdover from Tango's historical slowness) - measured instead of assumed,
issue #1321 records a prototype running the full lifecycle check against all
37 fields of Tango's equivalent device in 0.47s; EPICS is slower per-field
(real network round trips) but still cheap enough, and this file's own first
cut (curated to 7 fields, one commit prior on this branch) already proved the
pattern out.

A handful of fields intentionally sit outside this sweep: EPICS-specific
mechanism/precision/limits quirks (`longstr`, `float_prec_0`, `mbb_direct_bit`,
`bool_unnamed`, `enum_str_fallback`, ...) that don't generalise to a "one
value per datatype" table, and error/connection/plan-stub mechanics that
aren't datatype coverage at all - both folded forward into
`test_epics_signal_mechanisms.py` instead of being silently dropped when the
old `test_signals.py` (~1150 lines, mixing datatype coverage with EPICS
mechanism tests) was deleted.

Initial/put values and describe metadata below are the same values already
verified against a real IOC by the old `test_signals.py`'s `CA_PVA_INFERRED`/
`PVA_INFERRED` tables - copied rather than imported, since that module no
longer exists.
"""

import os
from pathlib import Path
from typing import Generic, TypeVar

import numpy as np
import pytest
import yaml
from aioca import purge_channel_caches
from bluesky.protocols import Location
from event_model import Limits, LimitsRange

from ophyd_async.core import (
    Array1D,
    NotConnectedError,
    SignalRW,
    Table,
    YamlSettingsProvider,
)
from ophyd_async.epics.core import epics_signal_rw
from ophyd_async.epics.testing import (
    IOC,
    EpicsTestCaDevice,
    EpicsTestEnum,
    EpicsTestPvaDevice,
    EpicsTestSubsetEnum,
    EpicsTestSupersetEnum,
    EpicsTestTable,
    generate_random_pv_prefix,
    start_ioc,
)
from ophyd_async.plan_stubs import (
    apply_settings,
    ensure_connected,
    retrieve_settings,
    store_settings,
)
from ophyd_async.testing import MonitorQueue, approx_value, assert_describe_signal

T = TypeVar("T")

TIMEOUT = 30.0 if os.name == "nt" else 3.0

HERE = Path(__file__).absolute().parent


class LifecycleIoc:
    """Owns the fixed EPICS test IOC catalog's prefix, one per module.

    Builds a fresh, unconnected `EpicsTestCaDevice`/`EpicsTestPvaDevice`
    against it on request - each test connects its own instance rather than
    sharing one across the whole module, mirroring
    `test_tango_signal_lifecycle.py`'s per-test `TangoTestDevice(trl, ...)`
    construction.

    `pvi=True` connects the *same* underlying PVs through the IOC's PVI
    directory instead of the static `PvSuffix` annotations - per issue
    #1321's design decision, this dimension is "nearly free": every field on
    both devices already has a matching PVI directory entry (proven by the
    old `test_signals.py`'s `test_ca_device_full_pvi_mirror`/
    `test_pva_device_full_pvi_mirror` - connecting via PVI requires 100% of
    annotated fields to resolve), so no new data-authoring is needed, just an
    extra parametrize dimension.
    """

    def __init__(self):
        self.prefix = generate_random_pv_prefix()

    def device(
        self, protocol: str, pvi: bool = False
    ) -> EpicsTestCaDevice | EpicsTestPvaDevice:
        cls = EpicsTestCaDevice if protocol == "ca" else EpicsTestPvaDevice
        prefix = f"{self.prefix}{protocol}:"
        if pvi:
            return cls(prefix, with_pvi=True)
        return cls(f"{protocol}://{prefix}")

    def pva_device(self, pvi: bool = False) -> EpicsTestPvaDevice:
        # Statically typed as EpicsTestPvaDevice, unlike device() above -
        # for callers (table/ntndarray tests below) that need pva-only
        # attributes, so pyright doesn't see the EpicsTestCaDevice half of
        # device()'s union return type and complain they're missing.
        prefix = f"{self.prefix}pva:"
        if pvi:
            return EpicsTestPvaDevice(prefix, with_pvi=True)
        return EpicsTestPvaDevice(f"pva://{prefix}")


@pytest.fixture(scope="module")
def ioc():
    ioc = LifecycleIoc()
    process = start_ioc(IOC, ioc.prefix)
    yield ioc
    # Purge the channel caches before we stop the IOC to stop
    # RuntimeError: Event loop is closed errors on teardown
    purge_channel_caches()
    process.stop()
    print(process.output)


class ExpectedData(Generic[T]):
    def __init__(self, initial: T, put: T, dtype: str, dtype_numpy: str, **metadata):
        self.initial = initial
        self.put = put
        self.metadata = dict(dtype=dtype, dtype_numpy=dtype_numpy, **metadata)


# Can be removed once numpy >=2 is pinned - see the old test_signals.py's
# identical scalar_int_dtype for the Windows/numpy<2 case this simplifies away.
_SCALAR_INT_DTYPE = "<i8"

# Fields common to ca:/pva: (pva can carry everything ca can - see
# EpicsTestPvaDevice's own docstring). Put values are chosen to be the same
# length/shape as their initial value for the array fields: assert_signal_
# lifecycle checks describe() is unchanged by a put, which wouldn't hold for
# a waveform record if the put shrank NORD.
SIGNAL_INFO: dict[str, ExpectedData] = {
    "a_int": ExpectedData(
        42,
        43,
        "integer",
        _SCALAR_INT_DTYPE,
        limits=Limits(
            control=LimitsRange(low=10, high=90),
            warning=LimitsRange(low=5, high=96),
            alarm=LimitsRange(low=2, high=98),
            display=LimitsRange(low=0, high=100),
        ),
        units="",
    ),
    "a_float": ExpectedData(3.141, 43.5, "number", "<f8", precision=1, units="mm"),
    "a_str": ExpectedData("hello", "goodbye", "string", "|S40"),
    "a_bool": ExpectedData(True, False, "boolean", "|b1"),
    "enum": ExpectedData(
        EpicsTestEnum.B,
        EpicsTestEnum.C,
        "string",
        "|S40",
        choices=["Aaa", "Bbb", "Ccc"],
    ),
    "subset_enum": ExpectedData(
        EpicsTestSubsetEnum.B,
        EpicsTestSubsetEnum.A,
        "string",
        "|S40",
        choices=["Aaa", "Bbb", "Ccc"],
    ),
    # superset_enum shares its backing PV with subset_enum (mbbo, choices
    # Aaa/Bbb/Ccc - see EpicsTestSupersetEnum's own docstring): describe()'s
    # choices come from the PV's *actual* choices, not the wider Python enum,
    # so this is identical metadata to subset_enum above. Genuinely untested
    # by any suite (old or new) before this - see issue #1321.
    "superset_enum": ExpectedData(
        EpicsTestSupersetEnum.B,
        EpicsTestSupersetEnum.C,
        "string",
        "|S40",
        choices=["Aaa", "Bbb", "Ccc"],
    ),
    "uint8a": ExpectedData(
        np.array([0, 255], dtype=np.uint8),
        np.array([218, 7], dtype=np.uint8),
        "array",
        "|u1",
        units="",
    ),
    "int16a": ExpectedData(
        np.array([-32768, 32767], dtype=np.int16),
        np.array([-855, 12345], dtype=np.int16),
        "array",
        "<i2",
        units="",
    ),
    "int32a": ExpectedData(
        np.array([-2147483648, 2147483647], dtype=np.int32),
        np.array([-2, 123456], dtype=np.int32),
        "array",
        "<i4",
        units="",
    ),
    "float32a": ExpectedData(
        np.array([0.000002, -123.123], dtype=np.float32),
        np.array([1.0, -2.5], dtype=np.float32),
        "array",
        "<f4",
        units="",
        precision=0,
    ),
    "float64a": ExpectedData(
        np.array([0.1, -12345678.123], dtype=np.float64),
        np.array([0.2, 999.999], dtype=np.float64),
        "array",
        "<f8",
        units="",
        precision=0,
    ),
    "stra": ExpectedData(
        ["five", "six", "seven"], ["nine", "ten", "eleven"], "array", "|S40"
    ),
}

# PVA-only array fields - EpicsTestPvaDevice adds these on top of everything
# in SIGNAL_INFO (see its own docstring: "pva can support all signal types
# that ca can").
PVA_ONLY_SIGNAL_INFO: dict[str, ExpectedData] = {
    "int8a": ExpectedData(
        np.array([-128, 127, 0, 1, 2, 3, 4], dtype=np.int8),
        np.array([-8, 3, 44, 0, 1, 2, 3], dtype=np.int8),
        "array",
        "|i1",
        units="",
    ),
    "uint16a": ExpectedData(
        np.array([0, 65535, 0, 1, 2, 3, 4], dtype=np.uint16),
        np.array([5666, 1, 2, 3, 4, 5, 6], dtype=np.uint16),
        "array",
        "<u2",
        units="",
    ),
    "uint32a": ExpectedData(
        np.array([0, 4294967295, 0, 1, 2, 3, 4], dtype=np.uint32),
        np.array([1022233, 1, 2, 3, 4, 5, 6], dtype=np.uint32),
        "array",
        "<u4",
        units="",
    ),
    "int64a": ExpectedData(
        np.array([-(2**63 - 1), 2**63 - 1, 0, 1, 2, 3, 4], dtype=np.int64),
        np.array([-3, 1, 2, 3, 4, 5, 6], dtype=np.int64),
        "array",
        "<i8",
        units="",
    ),
    "uint64a": ExpectedData(
        np.array([0, 2**63 - 1, 0, 1, 2, 3, 4], dtype=np.uint64),
        np.array([995444, 1, 2, 3, 4, 5, 6], dtype=np.uint64),
        "array",
        "<u8",
        units="",
    ),
}


async def assert_signal_lifecycle(
    signal: SignalRW, initial_value, put_value, metadata: dict
) -> None:
    """Exercise get/put/monitor/describe/locate on an already-connected signal."""
    if isinstance(initial_value, np.ndarray):
        shape = list(initial_value.shape)
    elif isinstance(initial_value, list):
        # Sequence[str] (stra) - a 1-D array shape, same as the waveform
        # array fields, just not a numpy dtype.
        shape = [len(initial_value)]
    else:
        shape = []

    describe_before = await signal.describe()
    await assert_describe_signal(signal, shape=shape, **metadata)

    with MonitorQueue(signal) as q:
        # get + monitor: initial value arrives on subscribe
        await q.assert_updates(initial_value)

        # locate (readback half only): setpoint isn't meaningful until
        # something has actually been set() through this signal.
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


# Build the full (protocol, pvi, field, data) matrix up front, same shape as
# the old test_signals.py's CA_PVA_INFERRED/PVA_INFERRED parametrize lists -
# every SIGNAL_INFO field for both ca:/pva:, plus PVA_ONLY_SIGNAL_INFO for
# pva: only, each doubled over static-PvSuffix vs PVI-discovered connection.
_ALL_FIELD_CASES = [
    (protocol, pvi, name, data)
    for protocol in ("ca", "pva")
    for pvi in (False, True)
    for name, data in SIGNAL_INFO.items()
] + [
    ("pva", pvi, name, data)
    for pvi in (False, True)
    for name, data in PVA_ONLY_SIGNAL_INFO.items()
]
_ALL_FIELD_IDS = [
    f"{protocol}{'-pvi' if pvi else ''}-{name}"
    for protocol, pvi, name, _ in _ALL_FIELD_CASES
]


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize(
    "protocol,pvi,field,data", _ALL_FIELD_CASES, ids=_ALL_FIELD_IDS
)
async def test_signal_lifecycle(
    ioc: LifecycleIoc, protocol: str, pvi: bool, field: str, data: ExpectedData
):
    device = ioc.device(protocol, pvi)
    await device.connect(timeout=TIMEOUT)
    signal = getattr(device, field)
    try:
        await assert_signal_lifecycle(signal, data.initial, data.put, data.metadata)
    finally:
        # Leave the record as we found it, in case anything else relies on
        # its initial value within this module-scoped IOC.
        await signal.set(data.initial)


async def assert_monitor_then_put(
    signal,
    initial_value,
    put_value,
    metadata: dict,
    signal_set=None,
):
    """get/put/monitor/describe, without the locate half of the full
    lifecycle helper above - used for `table`/`ntndarray` below, neither of
    which fits `assert_signal_lifecycle`'s "one PV, one value" shape (a
    structured multi-column value, and a PV that can't be written directly
    at all - see each test's own docstring).
    """
    if signal_set is None:
        assert isinstance(signal, SignalRW)
        signal_set = signal.set
    await signal.connect(timeout=TIMEOUT)
    with MonitorQueue(signal) as q:
        await q.assert_updates(initial_value)
        if isinstance(initial_value, np.ndarray):
            shape = list(initial_value.shape)
        elif isinstance(initial_value, list | Table):
            shape = [len(initial_value)]
        else:
            shape = []
        await assert_describe_signal(signal, shape=shape, **metadata)
        await signal_set(put_value)
        await q.assert_updates(put_value)


_TABLE_DTYPE_NUMPY = [
    ("a_bool", "|b1"),
    ("a_int", "<i4"),
    ("a_float", "<f8"),
    ("a_str", "|S40"),
    ("a_enum", "|S40"),
]
# Plain (non-EpicsTestTable) tables use the underlying EPICS datatype for
# columns the Table subclass would otherwise narrow - in this case a_bool
# stays uint8 rather than being narrowed to bool.
_PLAIN_TABLE_DTYPE_NUMPY = [
    ("a_bool", "|u1"),
    ("a_int", "<i4"),
    ("a_float", "<f8"),
    ("a_str", "|S40"),
    ("a_enum", "|S40"),
]


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("pvi", [False, True])
async def test_table_lifecycle(ioc: LifecycleIoc, pvi: bool):
    """`table` (pva-only) round-trips both an `EpicsTestTable` instance and a
    "plain" `Table` instance - proving `connect()` doesn't require the
    concrete subclass, it just picks which dtype each column decodes to.
    """
    device = ioc.pva_device(pvi)
    await device.connect(timeout=TIMEOUT)
    signal = device.table

    initial = EpicsTestTable(
        a_bool=np.array([False, False, True, True], np.bool_),
        a_int=np.array([1, 8, -9, 32], np.int32),
        a_float=np.array([1.8, 8.2, -6, 32.9887], np.float64),
        a_str=["Hello", "World", "Foo", "Bar"],
        a_enum=[EpicsTestEnum.A, EpicsTestEnum.B, EpicsTestEnum.A, EpicsTestEnum.C],
    )
    put = EpicsTestTable(
        a_bool=np.array([True, False], np.bool_),
        a_int=np.array([-5, 32], np.int32),
        a_float=np.array([8.5, -6.97], np.float64),
        a_str=["Hello", "Bat"],
        a_enum=[EpicsTestEnum.C, EpicsTestEnum.B],
    )
    await assert_monitor_then_put(
        signal, initial, put, {"dtype": "array", "dtype_numpy": _TABLE_DTYPE_NUMPY}
    )

    plain_initial = Table(
        a_bool=np.array([0, 0, 1, 1], np.uint8),
        a_int=np.array([1, 8, -9, 32], np.int32),
        a_float=np.array([1.8, 8.2, -6, 32.9887], np.float64),
        a_str=["Hello", "World", "Foo", "Bar"],
        a_enum=["Aaa", "Bbb", "Aaa", "Ccc"],
    )
    plain_put = Table(
        a_bool=np.array([1, 0], np.uint8),
        a_int=np.array([-5, 32], np.int32),
        a_float=np.array([8.5, -6.97], np.float64),
        a_str=["Hello", "Bat"],
        a_enum=["Ccc", "Bbb"],
    )
    guess_signal = epics_signal_rw(None, signal.source)  # type: ignore
    await assert_monitor_then_put(
        guess_signal,
        plain_put,
        plain_initial,
        {"dtype": "array", "dtype_numpy": _PLAIN_TABLE_DTYPE_NUMPY},
    )


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("pvi", [False, True])
async def test_ntndarray_lifecycle(ioc: LifecycleIoc, pvi: bool):
    """`ntndarray` (pva-only, bare `np.ndarray`) can't be `set()` directly:
    QSrv doesn't support writing an NTNDArray-shaped PV. Write via a
    "backdoor" raw `Array1D[np.int64]` signal at `<source>:data` instead -
    the same mechanism the old test_signals.py's `test_pva_ntndarray` used.
    """
    device = ioc.pva_device(pvi)
    await device.connect(timeout=TIMEOUT)
    signal = device.ntndarray

    raw_signal = epics_signal_rw(Array1D[np.int64], signal.source + ":data")
    await raw_signal.connect()

    async def signal_set(v):
        await raw_signal.set(v.flatten())

    initial = np.zeros((2, 3))
    put = np.arange(6).reshape((2, 3))
    metadata = {"dtype": "array", "dtype_numpy": "<i8"}
    await assert_monitor_then_put(signal, initial, put, metadata, signal_set)
    await assert_monitor_then_put(signal, put, initial, metadata, signal_set)


@pytest.mark.timeout(TIMEOUT)
async def test_writing_to_ndarray_raises_typeerror(ioc: LifecycleIoc):
    device = ioc.pva_device()
    await device.connect(timeout=TIMEOUT)
    signal = epics_signal_rw(np.ndarray, device.ntndarray.source)
    await signal.connect()
    with pytest.raises(TypeError):
        await signal.set(np.zeros((6,), dtype=np.int64))


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", ["ca", "pva"])
@pytest.mark.parametrize("pvi", [False, True])
async def test_go_command(ioc: LifecycleIoc, protocol: str, pvi: bool):
    device = ioc.device(protocol, pvi)
    await device.connect(timeout=TIMEOUT)
    await device.go.trigger()


# Mock-parity fields: every field SIGNAL_INFO/PVA_ONLY_SIGNAL_INFO/
# test_table_lifecycle cover - i.e. every RW datatype-in-scope field. Unlike
# the lifecycle sweep above, this deliberately excludes `ntndarray`
# (SignalR-only - the "get from real, set() onto mock" flow below needs a
# settable mock signal) and `go` (a Command, not a value-carrying Signal) -
# neither is curated away for coverage reasons, they just don't fit this
# specific check's shape.
CA_MOCK_PARITY_FIELDS = list(SIGNAL_INFO)
PVA_MOCK_PARITY_FIELDS = [*SIGNAL_INFO, *PVA_ONLY_SIGNAL_INFO, "table"]


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", ["ca", "pva"])
async def test_signal_mock_parity(ioc: LifecycleIoc, protocol: str):
    """A mock-connected device agrees on dtype with a real-connected one, and
    never touches the network for get/set. Exhaustive over every RW
    datatype-in-scope field - unlike Tango's curated declarative device (see
    that suite's module docstring), `EpicsTestCaDevice`/`EpicsTestPvaDevice`
    already declare every field with no procedural/declarative split to
    exploit, so there's no curation constraint here either.
    """
    real = ioc.device(protocol)
    mock = ioc.device(protocol)
    await real.connect(timeout=TIMEOUT)
    await mock.connect(mock=True)

    fields = CA_MOCK_PARITY_FIELDS if protocol == "ca" else PVA_MOCK_PARITY_FIELDS
    for field in fields:
        real_signal = getattr(real, field)
        mock_signal = getattr(mock, field)

        real_datakey = (await real_signal.describe())[real_signal.name]
        mock_datakey = (await mock_signal.describe())[mock_signal.name]
        assert real_datakey["dtype"] == mock_datakey["dtype"]

        # A value that's valid for the real signal is valid for its mock
        # twin, and setting it never reaches the real device.
        put_value = await real_signal.get_value()
        await mock_signal.set(put_value)
        assert approx_value(put_value) == await mock_signal.get_value()


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", ["ca", "pva"])
async def test_signal_error_paths(ioc: LifecycleIoc, protocol: str):
    """Representative, not exhaustive - see issue #1321's design decision:
    unlike get/put/monitor/describe/locate coverage, error-path coverage
    doesn't need every field, just one example per genuinely distinct
    failure mode.
    """
    device = ioc.device(protocol)
    await device.connect(timeout=TIMEOUT)

    # Right type, not a valid choice for a SubsetEnum signal. (Unlike Tango,
    # an EPICS mbb record's underlying write is a plain integer index, so a
    # wrong-Python-type set() like `device.enum.set(0)` doesn't error here -
    # 0 is simply accepted as "the choice at index 0" - there's no
    # EPICS-side equivalent of Tango's set()-time TypeError.)
    with pytest.raises(ValueError):
        await device.subset_enum.set("NOT_A_REAL_CHOICE")

    # Wrong inferred datatype at connect time: a_str is a string record.
    with pytest.raises(TypeError, match="cannot be coerced to int"):
        await epics_signal_rw(int, device.a_str.source).connect(timeout=TIMEOUT)

    # A well-formed PV that nothing is serving
    missing = epics_signal_rw(str, f"{protocol}://{ioc.prefix}{protocol}:no-such-pv")
    with pytest.raises(NotConnectedError):
        await missing.connect(timeout=0.2)


@pytest.mark.timeout(TIMEOUT + 0.5)
@pytest.mark.parametrize("protocol", ["ca", "pva"])
async def test_retrieve_apply_store_settings(
    RE, ioc: LifecycleIoc, protocol: str, tmp_path
):
    """Settings YAML round-trip, genericised onto the same widened device the
    rest of this file uses (this test itself is unchanged in substance from
    the old test_signals.py - the device it exercises was already exhaustive
    there too; `retrieve`/`apply`/`store_settings` operate on the whole
    Device regardless of which fields a given test file's sweep happens to
    touch individually, so the golden YAML files needed no regeneration).

    Placed last in this module: it round-trips *every* RW field on the
    device (via the golden YAML, not the SIGNAL_INFO initial values above),
    which would otherwise disturb the "leave the record as we found it"
    invariant the field-sweep tests above rely on for their own initial
    values if this test ran first.
    """
    tmp_provider = YamlSettingsProvider(tmp_path)
    expected_provider = YamlSettingsProvider(HERE)
    device = ioc.device(protocol)

    def a_plan():
        yield from ensure_connected(device)
        settings = yield from retrieve_settings(
            expected_provider, f"test_yaml_save_{protocol}", device
        )
        yield from apply_settings(settings)
        yield from store_settings(tmp_provider, "test_file", device)
        with open(tmp_path / "test_file.yaml") as actual_file:
            with open(HERE / f"test_yaml_save_{protocol}.yaml") as expected_file:
                # If this test fails because you added a signal, then you can regenerate
                # the test data with:
                # cp /tmp/pytest-of-root/pytest-current/test_retrieve_apply_store_sett0/test_file.yaml tests/system_tests/epics/core/test_yaml_save_ca.yaml  # noqa: E501
                # cp /tmp/pytest-of-root/pytest-current/test_retrieve_apply_store_sett1/test_file.yaml tests/system_tests/epics/core/test_yaml_save_pva.yaml  # noqa: E501
                assert yaml.safe_load(actual_file) == yaml.safe_load(expected_file)

    RE(a_plan())
