"""EPICS Signals over CA or PVA"""

from __future__ import annotations

from enum import Enum

try:
    from ._aioca import CaSignalBackend
except ImportError as ca_error:

    class CaSignalBackend:  # type: ignore
        def __init__(*args, ca_error=ca_error, **kwargs):
            raise NotImplementedError("CA support not available") from ca_error


try:
    from ._p4p import PvaSignalBackend
except ImportError as pva_error:

    class PvaSignalBackend:  # type: ignore
        def __init__(*args, pva_error=pva_error, **kwargs):
            raise NotImplementedError("PVA support not available") from pva_error


class _EpicsTransport(Enum):
    """The sorts of transport EPICS support"""

    #: Use Channel Access (using aioca library)
    ca = CaSignalBackend
    #: Use PVAccess (using p4p library)
    pva = PvaSignalBackend
