from __future__ import annotations

import asyncio
import time
from typing import Callable, List, Optional

from bluesky.protocols import Locatable, Location, Stoppable

from ophyd_async.core import AsyncStatus
from ophyd_async.tango import (
    TangoReadableDevice,
    tango_signal_r,
    tango_signal_rw,
    tango_signal_w,
    tango_signal_x,
)
from tango import DevState


# --------------------------------------------------------------------
class TangoMover(TangoReadableDevice, Locatable, Stoppable):
    # --------------------------------------------------------------------
    def __init__(self, trl: str, name="", signals: dict = None) -> None:
        """
        Generic moveable tango device. Can be used in combination with an appropriately
        formatted signal dictionary to instantiate any tango device that can be driven
        along a single axis.

        signals must be a dictionary that contains at least the following keys. Each key
        will be a signal of the same name on the device.
        - position
        - _state
        - _stop

        Values must be dictionaries of the following form
        {
            "dtype": "float",
            "source": "/position",
            "sig_type": "rw"
            "readable": True
            "configurable": True
            "read_uncached": False
        }

        Parameters
        ----------
        trl : str
            The Tango device trl
        name : str
            The name of the device
        signals : dict
            A dictionary containing the signals for the device
        """
        # Check that the signals dictionary is valid
        if not signals:
            raise ValueError("Signals dictionary must be provided")
        if "position" not in signals:
            raise ValueError("Signals dictionary must contain a position signal")
        if "_state" not in signals:
            raise ValueError("Signals dictionary must contain a _state signal")
        if "_stop" not in signals:
            raise ValueError("Signals dictionary must contain a _stop signal")

        self.position = None
        self._state = None
        self._stop = None
        self._signal_list = signals
        TangoReadableDevice.__init__(self, trl, name)
        self._set_success = True

    # --------------------------------------------------------------------
    def _add_signal(self, **kwargs: str) -> None:
        """
        Add a signal to the device

        Required Parameters
        ----------
        dtype : The data type of the value of the signal
        name : The name given to the signal object
        source : The source of the signal, appended to the device trl
        sig_type : The type of signal (r, w, rw, or x)
        """
        required_keys = ["dtype", "name", "source", "sig_type"]
        for key in required_keys:
            if key not in kwargs:
                raise ValueError(f"Missing required key {key}")
        dtype = kwargs["dtype"]
        name = kwargs["name"]
        source = kwargs["source"]
        sig_type = kwargs["sig_type"]

        # Convert the data type string to the actual type
        if dtype.lower() == "int":
            f_dtype = int
        elif dtype.lower() == "float":
            f_dtype = float
        elif dtype.lower() == "str":
            f_dtype = str
        elif dtype == "DevState":
            f_dtype = DevState
        elif dtype.lower() == "none":
            f_dtype = None
        else:
            raise ValueError(f"Invalid data type {dtype}")

        if sig_type == "r":
            setattr(
                self,
                name,
                tango_signal_r(f_dtype, self.trl + source, device_proxy=self.proxy),
            )
        elif sig_type == "w":
            setattr(
                self,
                name,
                tango_signal_w(f_dtype, self.trl + source, device_proxy=self.proxy),
            )
        elif sig_type == "rw":
            setattr(
                self,
                name,
                tango_signal_rw(f_dtype, self.trl + source, device_proxy=self.proxy),
            )
        elif sig_type == "x":
            setattr(
                self, name, tango_signal_x(self.trl + source, device_proxy=self.proxy)
            )
        else:
            raise ValueError(f"Invalid signal type {sig_type}")

    # --------------------------------------------------------------------
    def register_signals(self) -> None:
        # If signal names are not prepended by /, add it
        for name in self._signal_list:
            if not self._signal_list[name]["source"].startswith("/"):
                self._signal_list[name]["source"] = (
                    "/" + self._signal_list[name]["source"]
                )

        # If the dtype of the _state signal is not DevState, change it
        if self._signal_list["_state"]["dtype"] != "DevState":
            self._signal_list["_state"]["dtype"] = "DevState"

        # Parse the signal list and add the signals to the device
        for name, signal in self._signal_list.items():
            self._add_signal(name=name, **signal)

        # Set the readable signals
        self.set_readable_signals(
            read=[
                getattr(self, name)
                for name in self._signal_list
                if self._signal_list[name]["readable"]
            ],
            config=[
                getattr(self, name)
                for name in self._signal_list
                if self._signal_list[name]["configurable"]
            ],
            read_uncached=[
                getattr(self, name)
                for name in self._signal_list
                if self._signal_list[name]["read_uncached"]
            ],
        )

        self.set_name(self.name)

    # --------------------------------------------------------------------
    async def _move(
        self, new_position: float, watchers: List[Callable] or None = None
    ) -> None:
        if watchers is None:
            watchers = []
        self._set_success = True
        start = time.monotonic()
        start_position = await self.position.get_value()

        def update_watchers(current_position: float):
            for watcher in watchers:
                watcher(
                    name=self.name,
                    current=current_position,
                    initial=start_position,
                    target=new_position,
                    time_elapsed=time.monotonic() - start,
                )

        if self.position.is_cachable():
            self.position.subscribe_value(update_watchers)
        else:
            update_watchers(start_position)
        try:
            await self.position.set(new_position)
            await asyncio.sleep(0.1)
            counter = 0
            while await self._state.get_value() == DevState.MOVING:
                # Update the watchers with the current position every 0.5 seconds
                if counter % 5 == 0:
                    current_position = await self.position.get_value()
                    update_watchers(current_position)
                    counter = 0
                await asyncio.sleep(0.1)
                counter += 1
        finally:
            if self.position.is_cachable():
                self.position.clear_sub(update_watchers)
            else:
                update_watchers(await self.position.get_value())
        if not self._set_success:
            raise RuntimeError("Motor was stopped")

    # --------------------------------------------------------------------
    def set(self, new_position: float, timeout: Optional[float] = None) -> AsyncStatus:
        watchers: List[Callable] = []
        coro = asyncio.wait_for(self._move(new_position, watchers), timeout=timeout)
        return AsyncStatus(coro, watchers)

    # --------------------------------------------------------------------
    async def locate(self) -> Location:
        set_point = await self.position.get_setpoint()
        readback = await self.position.get_value()
        return Location(setpoint=set_point, readback=readback)

    # --------------------------------------------------------------------
    async def stop(self, success: bool = True) -> None:
        self._set_success = not success
        # Put with completion will never complete as we are waiting for completion on
        # the move above, so need to pass wait=False
        await self._stop.trigger()
