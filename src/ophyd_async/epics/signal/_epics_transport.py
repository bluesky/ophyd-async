"""EPICS Signals over CA or PVA"""

from __future__ import annotations

from enum import Enum


def _make_unavailable_class(error: Exception) -> type:
    class TransportNotAvailable:
        def __init__(*args, **kwargs):
            raise NotImplementedError("Transport not available") from error

    return TransportNotAvailable


try:
    from ._aioca import CaSignalBackend
except ImportError as ca_error:
    CaSignalBackend = _make_unavailable_class(ca_error)


try:
    from ._p4p import PvaSignalBackend
except ImportError as pva_error:
    PvaSignalBackend = _make_unavailable_class(pva_error)


class _EpicsTransport(Enum):
    """The sorts of transport EPICS support"""

    #: Use Channel Access (using aioca library)
    ca = CaSignalBackend
    #: Use PVAccess (using p4p library)
    pva = PvaSignalBackend
