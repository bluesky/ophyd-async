from __future__ import annotations

from typing import Tuple

from ophyd_async.core import (
    DEFAULT_TIMEOUT,
    ConfigSignal,
    HintedSignal,
    StandardReadable,
)
from ophyd_async.tango.base_devices._base_device import TangoDevice


def tango_polling(*args):
    """
    Class decorator to set polling for Tango devices. This is useful for device servers
    that do not support event-driven updates.
    """

    def decorator(cls):
        cls._polling = (True, *args)
        return cls

    return decorator


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

    async def connect(self, mock=False, timeout=DEFAULT_TIMEOUT, force_reconnect=False):
        await super().connect(mock=mock, timeout=timeout)
        if self._polling[0]:
            for sig in self._readables:
                if isinstance(sig, HintedSignal) or isinstance(sig, ConfigSignal):
                    backend = sig.signal._backend  # noqa: SLF001
                else:
                    backend = sig._backend  # noqa: SLF001
                backend.set_polling(*self._polling)
