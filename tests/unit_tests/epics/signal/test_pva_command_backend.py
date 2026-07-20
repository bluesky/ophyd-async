import pytest
from p4p import Value as P4PValue
from p4p.nt import NTScalar

from ophyd_async.epics.core import _p4p  # noqa: PLC2701
from ophyd_async.epics.core._p4p import PvaCommandBackend  # noqa: PLC2701


async def test_pva_command_backend_accepts_bool_pv(
    monkeypatch: pytest.MonkeyPatch,
):
    async def pvget_with_timeout(pv: str, timeout: float):
        return P4PValue(NTScalar.buildType("?"), {"value": True})

    monkeypatch.setattr(_p4p, "pvget_with_timeout", pvget_with_timeout)

    await PvaCommandBackend("BOOL").connect(timeout=1.0)
