from enum import Enum
from typing import Any, Dict, Generator, List, Optional, Union

import yaml
from bluesky import Msg
from numpy import ndarray

from ophyd_async.core import Device, SignalRW


def get_signal_values(
    signals: Dict[str, SignalRW], ignore: Optional[List[str]] = None
) -> Union[Generator[Dict[str, Any], None, None], Dict[str, Any]]:
    """
    Read the values of SignalRW's, to be used alongside `walk_rw_signals`. Used as part
    of saving a device
    Parameters
    ----------
        signals : Dict[str, SignalRW]: A dictionary matching the string attribute path
        of a SignalRW to the signal itself

        ignore : List of strings: . A list of string attribute paths to the SignalRW's
        to be ignored. Defaults to None.

    Returns
    ----------
        Dict[str, Any]: A dictionary matching the string attribute path of a SignalRW
        to the value of that signal

    Yields:
        Iterator[Dict[str, Any]]: The Location of a signal

    See Also
    --------
    :func:`ophyd_async.core.walk_rw_signals`
    :func:`ophyd_async.core.save_to_yaml`

    """

    if ignore is None:
        ignore = [""]

    values = yield Msg("locate", *signals.values())
    assert values is not None, "No signalRW's found"
    values = [value["setpoint"] for value in values]
    signal_name_to_val: Dict[str, Any] = {}
    for index, key in enumerate(signals.keys()):
        if key in ignore:
            continue
        signal_name_to_val[key] = values[index]
    return signal_name_to_val


def walk_rw_signals(
    device: Device, path_prefix: Optional[str] = None
) -> Dict[str, SignalRW]:
    """
    Get all the SignalRWs from a device and store them with their dotted attribute
    paths in a dictionary. Used as part of saving and loading a device
    Parameters
    ----------
    device : Device
        Ophyd device to retrieve read-write signals from.

    path_prefix : str
        For internal use, leave blank when calling the method.

    Returns
    -------
    SignalRWs : dict
        A dictionary matching the string attribute path of a SignalRW with the
        signal itself.

        See Also
    --------
    :func:`ophyd_async.core.get_signal_values`
    :func:`ophyd_async.core.save_to_yaml`

    """

    if not path_prefix:
        path_prefix = ""

    signals: Dict[str, SignalRW] = {}
    for attr_name, attr in device.children():
        dot_path = f"{path_prefix}{attr_name}"
        if type(attr) is SignalRW:
            signals[dot_path] = attr
        attr_signals = walk_rw_signals(attr, path_prefix=dot_path + ".")
        signals.update(attr_signals)
    return signals


def save_to_yaml(phases: Union[Dict, List[Dict]], save_path: str):
    """Serialises and saves a phase or a set of phases of a device's SignalRW's to a
    yaml file.

    Parameters
    ----------
    phases : dict or list of dicts
        The values to save. Each item in the list is a seperate phase used when loading
        a device. In general this variable be the return value of `get_signal_values`.

    save_path : str

    See Also
    --------
    :func:`ophyd_async.core.walk_rw_signals`
    :func:`ophyd_async.core.get_signal_values`
    """

    if isinstance(phases, dict):
        phases = [phases]
    phase_outputs = []
    for phase in phases:
        # The table PVs are dictionaries of np arrays. Need to convert these to
        # lists for easy saving
        for key, value in phase.items():
            if isinstance(value, dict):
                for inner_key, inner_value in value.items():
                    if isinstance(inner_value, ndarray):
                        value[inner_key] = inner_value.tolist()
            # Convert enums to their value
            elif isinstance(value, Enum):
                assert isinstance(
                    value.value, str
                ), "Enum value did not evaluate to string"
                phase[key] = value.value
        phase_outputs.append(phase)

    with open(save_path, "w") as file:
        yaml.dump(phase_outputs, file)
