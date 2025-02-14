from __future__ import annotations

from ophyd_async.core import StandardReadable
from tango import DeviceProxy

from ._base_device import TangoDevice


class TangoReadable(TangoDevice, StandardReadable):
    def __init__(
        self,
        trl: str | None = None,
        device_proxy: DeviceProxy | None = None,
        name: str = "",
    ) -> None:
        TangoDevice.__init__(self, trl, device_proxy=device_proxy, name=name)
