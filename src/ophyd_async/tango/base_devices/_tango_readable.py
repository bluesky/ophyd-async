from __future__ import annotations

from typing import Tuple

from ophyd_async.core import (
    StandardReadable,
)
from ophyd_async.tango.base_devices._base_device import TangoDevice


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

    # --------------------------------------------------------------------
    _polling: Tuple = (False, 0.1, None, 0.1)

    def __init__(self, trl: str, name="") -> None:
        TangoDevice.__init__(self, trl, name=name)
