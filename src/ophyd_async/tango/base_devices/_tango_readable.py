from __future__ import annotations

from ophyd_async.core import (
    StandardReadable,
)
from ophyd_async.tango.base_devices._base_device import TangoDevice
from tango import DeviceProxy


class TangoReadable(TangoDevice, StandardReadable):
    """
    General class for readable TangoDevices. Extends StandardReadable to provide
    attributes for Tango devices.

    Usage: to proper signals mount should be awaited:
    new_device = await TangoDevice(<tango_device>)

    Attributes
    ----------
    trl : str
        Tango resource locator, typically of the device server.
    proxy : AsyncDeviceProxy
        AsyncDeviceProxy object for the device. This is created when the
        device is connected.
    """

    def __init__(
        self,
        trl: str | None = None,
        device_proxy: DeviceProxy | None = None,
        name: str = "",
    ) -> None:
        TangoDevice.__init__(self, trl, device_proxy=device_proxy, name=name)
