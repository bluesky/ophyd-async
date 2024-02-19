from typing import Callable, Dict, FrozenSet, Optional, Type, TypedDict, TypeVar

from ophyd_async.core.signal import Signal
from ophyd_async.core.signal_backend import SignalBackend
from ophyd_async.core.utils import DEFAULT_TIMEOUT
from ophyd_async.epics._backend._p4p import PvaSignalBackend
from ophyd_async.epics.signal.signal import (
    epics_signal_r,
    epics_signal_rw,
    epics_signal_w,
    epics_signal_x,
)

T = TypeVar("T")


_pvi_mapping: Dict[FrozenSet[str], Callable[..., Signal]] = {
    frozenset({"r", "w"}): lambda dtype, read_pv, write_pv: epics_signal_rw(
        dtype, read_pv, write_pv
    ),
    frozenset({"rw"}): lambda dtype, read_pv, write_pv: epics_signal_rw(
        dtype, read_pv, write_pv
    ),
    frozenset({"r"}): lambda dtype, read_pv, _: epics_signal_r(dtype, read_pv),
    frozenset({"w"}): lambda dtype, _, write_pv: epics_signal_w(dtype, write_pv),
    frozenset({"x"}): lambda _, __, write_pv: epics_signal_x(write_pv),
}


class PVIEntry(TypedDict, total=False):
    d: str
    r: str
    rw: str
    w: str
    x: str


async def pvi_get(
    read_pv: str, timeout: float = DEFAULT_TIMEOUT
) -> Dict[str, PVIEntry]:
    """Makes a PvaSignalBackend purely to connect to PVI information.

    This backend is simply thrown away at the end of this method. This is useful
    because the backend handles a CancelledError exception that gets thrown on
    timeout, and therefore can be used for error reporting."""
    backend: SignalBackend = PvaSignalBackend(None, read_pv, read_pv)
    await backend.connect(timeout=timeout)
    d: Dict[str, Dict[str, Dict[str, str]]] = await backend.get_value()
    pv_info = d.get("pvi") or {}
    result = {}

    for attr_name, attr_info in pv_info.items():
        result[attr_name] = PVIEntry(**attr_info)  # type: ignore

    return result


def make_signal(signal_pvi: PVIEntry, dtype: Optional[Type[T]] = None) -> Signal[T]:
    """Make a signal.

    This assumes datatype is None so it can be used to create dynamic signals.
    """
    operations = frozenset(signal_pvi.keys())
    pvs = [signal_pvi[i] for i in operations]  # type: ignore
    signal_factory = _pvi_mapping[operations]

    write_pv = "pva://" + pvs[0]
    read_pv = write_pv if len(pvs) < 2 else "pva://" + pvs[1]

    return signal_factory(dtype, read_pv, write_pv)
