"""Base device"""
from __future__ import annotations

import asyncio
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional, Tuple

import yaml
from bluesky.protocols import HasName
from numpy import ndarray

from ophyd_async.core import AsyncStatus, SignalRW

from ..utils import wait_for_connection


class Device(HasName):
    """Common base class for all Ophyd Async Devices.

    By default, names and connects all Device children.
    """

    _name: str = ""
    #: The parent Device if it exists
    parent: Optional[Device] = None

    def __init__(self, name: str = "") -> None:
        self.set_name(name)

    @property
    def name(self) -> str:
        """Return the name of the Device"""
        return self._name

    def children(self) -> Iterator[Tuple[str, Device]]:
        for attr_name, attr in self.__dict__.items():
            if attr_name != "parent" and isinstance(attr, Device):
                yield attr_name, attr

    def set_name(self, name: str):
        """Set ``self.name=name`` and each ``self.child.name=name+"-child"``.

        Parameters
        ----------
        name:
            New name to set
        """
        self._name = name
        for attr_name, child in self.children():
            child_name = f"{name}-{attr_name.rstrip('_')}" if name else ""
            child.set_name(child_name)
            child.parent = self

    async def connect(self, sim: bool = False):
        """Connect self and all child Devices.

        Parameters
        ----------
        sim:
            If True then connect in simulation mode.
        """
        coros = {
            name: child_device.connect(sim) for name, child_device in self.children()
        }
        if coros:
            await wait_for_connection(**coros)


def get_signal_RWs_from_device(
    device: Device, prefix: str, signalRWs: Dict[str, SignalRW] = {}
) -> Dict[str, SignalRW]:
    """Get all the signalRW's from a device and store with their dotted attribute paths.
    Used by the save_device and load_device methods.

    Parameters
    ----------
        device: Device
            Ophyd device to retrieve read write signals from

        prefix: Str
            Device prefix

        SignalRWs: Dict
            A dictionary matching the string attribute path of a SignalRW with the
            signal itself. Leave blank when calling method.

    Returns:
        SignalRWs: Dict
            A dictionary matching the string attribute path of a SignalRW with the
            signal itself.
    """

    for attr_name, attr in device.children:
        dot = ""
        # Place a dot inbetween the upper and lower class.
        # Don't do this for highest level class.
        if prefix:
            dot = "."
        dot_path = f"{prefix}{dot}{attr_name}"
        if type(attr) is SignalRW:
            signalRWs[dot_path] = attr
        get_signal_RWs_from_device(attr, prefix=dot_path)
    return signalRWs


async def save_device(device: Device, savename: str):
    """
    Save the setup of a device by getting a list of its signals and their readback
    values. Stores the output to savename.yaml

    Parameters
    ----------
    device : Savable
        Ophyd device which implements the sort_signal_by_phase method.

    savename: String
        name of yaml file

    md : dict, optional
        metadata

    Yields
    ------
    msg : Msg
        'locate', *signals

    See Also
    --------
    :func:`ophyd_async.core.load_device`
    """

    signalRWs: Dict[str, SignalRW] = get_signal_RWs_from_device(device, "")

    if len(signalRWs):
        # Same as signalRWs, but ordered by phase TODO: most devices wont have an order
        phase_dicts: List[Dict[str, SignalRW]] = device.sort_signal_by_phase(signalRWs)

        # Locate all signals in parallel
        signal_values: List[SignalRW] = []
        if len(phase_dicts):
            for phase in phase_dicts:
                for value in phase.values():
                    signal_values.append(value.locate())
            signal_values = await asyncio.gather(*signal_values)

        # The table PVs are dictionaries of np arrays. Need to convert these to lists
        # for easy saving TODO: find out proper way to deal with panda 'TABLES'
        for index, value in enumerate(signal_values):
            if isinstance(value, dict):
                for inner_key, inner_value in value.items():
                    if isinstance(inner_value, ndarray):
                        value[inner_key] = inner_value.tolist()
            # Convert enums to their values
            elif isinstance(signal_values[index], Enum):
                signal_values[index] = value.value

        # For each phase, save a dictionary containing the phases' dotted signalRW
        # paths and their values
        phase_outputs: List[Dict[str, Any]] = []
        signal_value_index = 0
        for phase in phase_dicts:
            signal_name_values: Dict[str, Any] = {}
            for signal_name in phase.keys():
                signal_name_values[signal_name] = signal_values[signal_value_index]
                signal_value_index += 1
            phase_outputs.append(signal_name_values)

        filename = f"{savename}.yaml"
        with open(filename, "w") as file:
            yaml.dump(phase_outputs, file)


async def load_device(device, savename: str):
    """Does an abs_set on each signalRW which has differing values to the savefile"""

    # Locate all signals to later compare with loaded values, then only
    # change differing values

    signalRWs: Dict[str, SignalRW] = get_signal_RWs_from_device(
        device, ""
    )  # {'device.subdevice.etc: signalRW}
    signal_name_values = (
        {}
    )  # we want this to be {'device.subdevice.etc: signal location}
    signals_to_locate = []
    for sig in signalRWs.values():
        signals_to_locate.append(sig.locate())

    signal_values = await asyncio.gather(*signals_to_locate)

    # Copy logic from save plan to convert enums and np arrays
    for index, value in enumerate(signal_values):
        if isinstance(value, dict):
            for inner_key, inner_value in value.items():
                if isinstance(inner_value, ndarray):
                    value[inner_key] = inner_value.tolist()
        # Convert enums to their values
        elif isinstance(signal_values[index], Enum):
            signal_values[index] = value.value

    for index, key in enumerate(signalRWs.keys()):
        signal_name_values[key] = signal_values[index]

    # Get PV info from yaml file
    filename = f"{savename}.yaml"
    with open(filename, "r") as file:
        data_by_phase: List[Dict[str, Any]] = yaml.full_load(file)

        """For each phase, find the location of the SignalRW's in that phase, load them 
        to the correct value, and wait for the load to complete"""
        for phase_number, phase in enumerate(data_by_phase):
            phase_load_statuses: List[AsyncStatus] = []
            for key, value in phase.items():
                # If the values are different then do an abs_set
                if signal_name_values[key] != value:
                    # Key is subdevices_x.subdevices_x+1.etc.signalname. First get
                    # the attribute hierarchy
                    components = key.split(".")
                    lowest_device = device

                    # If there are subdevices
                    if len(components) > 1:
                        signal_name: str = components[
                            -1
                        ]  # Last string is the signal name
                        for attribute in components[:-1]:
                            lowest_device = getattr(lowest_device, attribute)
                    else:
                        signal_name: str = components[0]
                    signalRW: SignalRW = getattr(lowest_device, signal_name)

                    phase_load_statuses.append(signalRW.set(value, timeout=5))

            await asyncio.gather(*phase_load_statuses)
