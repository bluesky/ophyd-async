from enum import Enum
from typing import Any, Dict, List

import yaml
from bluesky import Msg
from numpy import ndarray

from ophyd_async.core import Device, SignalRW


def get_signal_RWs_from_device(
    device: Device, path_prefix: str = "", signalRWs: Dict[str, SignalRW] = {}
) -> Dict[str, SignalRW]:
    """
    Get all the SignalRWs from a device and store them with their dotted attribute
    paths. Used by the save and load methods.

    Parameters
    ----------
    device : Device
        Ophyd device to retrieve read-write signals from.

    path_prefix : str
        For internal use, leave blank when calling the method.

    SignalRWs : dict
        A dictionary matching the string attribute path of a SignalRW with the
        signal itself. Leave blank when calling the method.

    Returns
    -------
    SignalRWs : dict
        A dictionary matching the string attribute path of a SignalRW with the
        signal itself.
    """

    for attr_name, attr in device.children():
        dot = ""
        # Place a dot inbetween the upper and lower class.
        # Don't do this for highest level class.
        if path_prefix:
            dot = "."
        dot_path = f"{path_prefix}{dot}{attr_name}"
        if type(attr) is SignalRW:
            signalRWs[dot_path] = attr
        get_signal_RWs_from_device(attr, path_prefix=dot_path)
    return signalRWs


def save_device(device: Device, savename: str, ignore: List[str] = []):
    """
    Plan to save the setup of a device by getting a list of its signals and their
    readback values.

    Store the output to a yaml file ``savename.yaml``

    Parameters
    ----------
    device : Device

    savename : str
        Name of the YAML file.

    ignore : list of str
        List of attribute path strings to not include in the save file.

    Yields
    ------
    msg : Msg
        ``locate``, ``*signals``

    See Also
    --------
    :func:`ophyd_async.core.load_device_plan`
    :func:`ophyd_async.core.load_device`
    :func:`sort_signal_by_phase`
    """

    signalRWs: Dict[str, SignalRW] = get_signal_RWs_from_device(device, "")

    # Get list of signalRWs ordered by phase
    phase_dicts: List[Dict[str, SignalRW]] = []
    if len(signalRWs):
        if hasattr(device, "sort_signal_by_phase"):
            phase_dicts = device.sort_signal_by_phase(device, signalRWs)
        else:
            phase_dicts.append(signalRWs)

        # Locate all signals in parallel
        signals_to_locate: List[SignalRW] = []
        for phase in phase_dicts:
            signals_to_locate.extend(phase.values())
        signal_values = yield Msg("locate", *signals_to_locate)
        signal_values = [value["setpoint"] for value in signal_values]

        # The table PVs are dictionaries of np arrays. Need to convert these to
        # lists for easy saving
        for index, value in enumerate(signal_values):
            if isinstance(value, dict):
                for inner_key, inner_value in value.items():
                    if isinstance(inner_value, ndarray):
                        value[inner_key] = inner_value.tolist()
            # Convert enums to their values
            elif isinstance(signal_values[index], Enum):
                signal_values[index] = value.value

        # For each phase, save a dictionary containing the phases'
        # dotted signalRW paths and their values
        phase_outputs: List[Dict[str, Any]] = []
        signal_value_index = 0
        for phase in phase_dicts:
            signal_name_values: Dict[str, Any] = {}
            for signal_name in phase.keys():
                if signal_name not in ignore:
                    signal_name_values[signal_name] = signal_values[signal_value_index]
                signal_value_index += 1

            phase_outputs.append(signal_name_values)

        filename = f"{savename}.yaml"
        with open(filename, "w") as file:
            yaml.dump(phase_outputs, file)
