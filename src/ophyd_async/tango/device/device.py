"""Default Tango Devices"""

from __future__ import annotations

from inspect import isclass
from typing import get_type_hints, Union, Generic, Tuple, Sequence, Type, get_origin, get_args

from tango import AttrWriteType, CmdArgType
from tango.asyncio import DeviceProxy

from ophyd_async.core import StandardReadable, SignalW, SignalX, SignalR, SignalRW, Signal, T
from ophyd_async.tango.signal import tango_signal_r, tango_signal_rw, tango_signal_w, tango_signal_x

__all__ = ("TangoDevice",
           "TangoStandardReadableDevice",
           "ReadableSignal",
           "ReadableUncachedSignal",
           "ConfigurableSignal")


# --------------------------------------------------------------------

class _AutoSignal(Signal):
    """
    To mark attribute/command in devices type hits as the one, which has to be read every step
    """


# --------------------------------------------------------------------
class ReadableSignal(_AutoSignal, Generic[T]):
    """
    To mark attribute/command in devices type hits as the one, which has to be read every step
    """

    _add_me_to = "_read_signals"


# --------------------------------------------------------------------
class ReadableUncachedSignal(_AutoSignal, Generic[T]):
    """
    To mark attribute/command in devices type hits as the one, which has to be read every step
    """

    _add_me_to = "_read_uncached_signals"


# --------------------------------------------------------------------
class ConfigurableSignal(_AutoSignal, Generic[T]):
    """
    To mark attribute/command in devices type hits as the one, which has to be read only as startup
    """

    _add_me_to = "_configuration_signals"


# --------------------------------------------------------------------
def get_signal(dtype: Type[T], name: str, trl: str, device_proxy: DeviceProxy) -> Union[SignalW, SignalX, SignalR, SignalRW]:
    ftrl = trl + '/' + name
    if name in device_proxy.get_attribute_list():
        conf = device_proxy.get_attribute_config(name, green_mode=False)

        if conf.writable in [AttrWriteType.READ_WRITE, AttrWriteType.READ_WITH_WRITE]:
            return tango_signal_rw(dtype, ftrl, ftrl, device_proxy)
        elif conf.writable == AttrWriteType.READ:
            return tango_signal_r(dtype, ftrl, device_proxy)
        else:
            return tango_signal_w(dtype, ftrl, device_proxy)
    if name in device_proxy.get_command_list():
        # TODO: check logic
        conf = device_proxy.get_command_config(name, green_mode=False)
        if conf.in_type == CmdArgType.DevVoid:
            return tango_signal_x(ftrl, device_proxy)
        elif conf.out_type != CmdArgType.DevVoid:
            return tango_signal_rw(dtype, ftrl, ftrl, device_proxy)
        else:
            return tango_signal_r(dtype, ftrl, device_proxy)

    if name in device_proxy.get_pipe_list():
        raise NotImplemented("Pipes are not supported")

    raise RuntimeError(f"{name} cannot be found in {device_proxy.name()}")


# --------------------------------------------------------------------
class TangoDevice:
    """
    General class for TangoDevices

    Usage: to proper signals mount should be awaited:

    new_device = await TangoDevice(<tango_device>)
    """

    # --------------------------------------------------------------------
    def __init__(self, trl: str) -> None:
        self.trl = trl
        self.proxy: DeviceProxy = None

    # --------------------------------------------------------------------
    def __await__(self):
        async def closure():
            self.proxy = await DeviceProxy(self.trl)
            hints = get_type_hints(self)
            signals = {}
            for name, dtype in hints.items():
                add_to = None
                origin = get_origin(dtype)
                if isclass(origin) and issubclass(origin, _AutoSignal):
                    add_to = origin._add_me_to
                    dtype = get_args(dtype)[0]
                signal = get_signal(dtype, name, self.trl, self.proxy)  # type: ignore
                setattr(self, name, signal)
                if add_to:
                    if add_to not in signals:
                        signals[add_to] = [getattr(self, name)]
                    else:
                        signals[add_to].append(getattr(self, name))
            for name, signals_set in signals.items():
                setattr(self, name, tuple(signals_set))

            self.register_signals()

            return self

        return closure().__await__()

    # --------------------------------------------------------------------
    def register_signals(self):
        """
        This method can be used to manually register signals
        """


# --------------------------------------------------------------------
class TangoStandardReadableDevice(TangoDevice, StandardReadable):

    _read_signals: Tuple[Union[SignalR, SignalRW], ...] = ()
    _configuration_signals: Tuple[Union[SignalR, SignalRW], ...] = ()
    _read_uncached_signals: Tuple[Union[SignalR, SignalRW], ...] = ()

    # --------------------------------------------------------------------
    def __init__(self, trl: str, name="") -> None:
        TangoDevice.__init__(self, trl)
        StandardReadable.__init__(self, name=name)

    # --------------------------------------------------------------------
    def set_readable_signals(
        self,
        read: Sequence[Union[SignalR, SignalRW]] = (),
        config: Sequence[Union[SignalR, SignalRW]] = (),
        read_uncached: Sequence[Union[SignalR, SignalRW]] = (),
    ):
        """
        Parameters
        ----------
        read:
            Signals to make up :meth:`~StandardReadable.read`
        config:
            Signals to make up :meth:`~StandardReadable.read_configuration`
        read_uncached:
            Signals to make up :meth:`~StandardReadable.read` that won't be cached
        """
        self._read_signals = tuple(read)
        self._configuration_signals = tuple(config)
        self._read_uncached_signals = tuple(read_uncached)

