from __future__ import annotations

from typing import Optional

from ophyd_async.core import T, SignalW, SignalRW
from ophyd_async.core.signal import add_timeout


# --------------------------------------------------------------------
# from tango attributes one can get setvalue, so we extend SignalRW and SignalW to add it
class SignalWithSetpoit:
    @add_timeout
    async def get_setpoint(self, cached: Optional[bool] = None) -> T:
        """The last written value to TRL"""
        return await self._backend_or_cache(cached).get_w_value()


# --------------------------------------------------------------------
class TangoSignalW(SignalW[T], SignalWithSetpoit):
    ...


# --------------------------------------------------------------------
class TangoSignalRW(SignalRW[T], SignalWithSetpoit):
    ...
