from __future__ import annotations

from typing import Optional, Tuple, Union

from ophyd_async.core import (
    StandardReadable,
)
from ophyd_async.tango.base_devices._base_device import TangoDevice
from tango import DeviceProxy as SyncDeviceProxy
from tango.asyncio import DeviceProxy as AsyncDeviceProxy


class TangoReadable(TangoDevice, StandardReadable):
    """
    General class for readable TangoDevices. Extends StandardReadable to provide
    attributes for Tango devices.

    Usage: to proper signals mount should be awaited:
    new_device = await TangoDevice(<tango_device>)

    attributes:
        trl:        Tango resource locator, typically of the device server.
        proxy:      AsyncDeviceProxy object for the device. This is created when the
                    device is connected.
    """

    _polling: Tuple = (False, 0.1, None, 0.1)

    def __init__(
        self,
        trl: Optional[str] = None,
        device_proxy: Optional[Union[AsyncDeviceProxy, SyncDeviceProxy]] = None,
        name: str = "",
    ) -> None:
        TangoDevice.__init__(self, trl, device_proxy=device_proxy, name=name)
