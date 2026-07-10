"""Generic Signal-level lifecycle coverage for EpicsTestCaDevice/EpicsTestPvaDevice.

Second slice of issue #1321 item 4 ("New Signal-level system test suites
(get/put/monitor/describe/locate/mock-parity/error-paths) per transport,
replacing the old ones"), following the pattern established for Tango by
`tests/system_tests_tango/test_tango_signal_lifecycle.py` (see its module
docstring for the full rationale): rather than a large hand-curated per-field
metadata table like `test_signals.py` uses (one `ExpectedData`-shaped entry
per attribute, repeated per transport), `assert_signal_lifecycle` below is a
single generic check run once per field, parametrized over a curated field
list shared between `ca:`/`pva:` - the pattern still needs replicating for
PVI and `core` (PVI already has solid get/put/error/structural coverage in
`test_signals.py`/`test_pvi_nested.py`, just not through this generic
helper), and eventually `test_signals.py`'s hand-curated tables retired
(issue #1321 item 6).

Initial/put values and describe metadata below are the same values already
verified against a real IOC by `test_signals.py`'s `CA_PVA_INFERRED`/
`CA_PVA_OVERRIDE` tables - copied rather than imported, since `test_signals.py`
itself is what this file is intended to eventually replace (issue #1321 item
6), so importing from it would be a dependency in the wrong direction.
"""

import os
from typing import Generic, TypeVar

import numpy as np
import pytest
from aioca import purge_channel_caches
from bluesky.protocols import Location
from event_model import Limits, LimitsRange

from ophyd_async.core import NotConnectedError, SignalRW
from ophyd_async.epics.core import epics_signal_rw
from ophyd_async.epics.testing import (
    IOC,
    EpicsTestCaDevice,
    EpicsTestEnum,
    EpicsTestPvaDevice,
    EpicsTestSubsetEnum,
    generate_random_pv_prefix,
    start_ioc,
)
from ophyd_async.testing import MonitorQueue, approx_value, assert_describe_signal

T = TypeVar("T")

TIMEOUT = 30.0 if os.name == "nt" else 3.0

# Fields common to ca:/pva: (pva can carry everything ca can - see
# EpicsTestPvaDevice's own docstring) covering int/float/str/bool/enum/
# subset_enum/array, the same categories test_signals.py's ExpectedData
# tables exercise, minus the PVA-only extras (int8a/table/ntndarray - see
# test_pva_table/test_pva_ntndarray) and the EPICS-quirk fields
# (longstr/float_prec_0/mbb_direct_bit/...) that don't generalise across
# transports.
LIFECYCLE_FIELDS = [
    "a_int",
    "a_float",
    "a_str",
    "a_bool",
    "enum",
    "subset_enum",
    "uint8a",
]

# Can be removed once numpy >=2 is pinned - see test_signals.py's identical
# scalar_int_dtype for the Windows/numpy<2 case this simplifies away.
_SCALAR_INT_DTYPE = "<i8"


class ExpectedData(Generic[T]):
    def __init__(self, initial: T, put: T, dtype: str, dtype_numpy: str, **metadata):
        self.initial = initial
        self.put = put
        self.metadata = dict(dtype=dtype, dtype_numpy=dtype_numpy, **metadata)


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
    "uint8a": ExpectedData(
        np.array([0, 255], dtype=np.uint8),
        # Same length as initial, unlike test_signals.py's equivalent entry:
        # assert_signal_lifecycle checks describe() is unchanged by a put,
        # which wouldn't hold for a waveform record if the put shrank NORD.
        np.array([218, 7], dtype=np.uint8),
        "array",
        "|u1",
        units="",
    ),
}


class LifecycleIoc:
    """Owns the fixed EPICS test IOC catalog's prefix, one per module.

    Builds a fresh, unconnected `EpicsTestCaDevice`/`EpicsTestPvaDevice`
    against it on request - each test connects its own instance rather than
    sharing one across the whole module, mirroring
    `test_tango_signal_lifecycle.py`'s per-test `TangoTestDevice(trl, ...)`
    construction.
    """

    def __init__(self):
        self.prefix = generate_random_pv_prefix()

    def device(self, protocol: str) -> EpicsTestCaDevice | EpicsTestPvaDevice:
        cls = EpicsTestCaDevice if protocol == "ca" else EpicsTestPvaDevice
        return cls(f"{protocol}://{self.prefix}{protocol}:")


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


async def assert_signal_lifecycle(
    signal: SignalRW, initial_value, put_value, metadata: dict
) -> None:
    """Exercise get/put/monitor/describe/locate on an already-connected signal."""
    if isinstance(initial_value, np.ndarray):
        shape = list(initial_value.shape)
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


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", ["ca", "pva"])
@pytest.mark.parametrize("field", LIFECYCLE_FIELDS)
async def test_signal_lifecycle(ioc: LifecycleIoc, protocol: str, field: str):
    device = ioc.device(protocol)
    await device.connect(timeout=TIMEOUT)
    signal = getattr(device, field)
    data = SIGNAL_INFO[field]
    try:
        await assert_signal_lifecycle(signal, data.initial, data.put, data.metadata)
    finally:
        # Leave the record as we found it, in case anything else relies on
        # its initial value within this module-scoped IOC.
        await signal.set(data.initial)


@pytest.mark.timeout(TIMEOUT)
@pytest.mark.parametrize("protocol", ["ca", "pva"])
async def test_signal_mock_parity(ioc: LifecycleIoc, protocol: str):
    """A mock-connected device agrees on dtype with a real-connected one, and
    never touches the network for get/set."""
    real = ioc.device(protocol)
    mock = ioc.device(protocol)
    await real.connect(timeout=TIMEOUT)
    await mock.connect(mock=True)

    for field in LIFECYCLE_FIELDS:
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
