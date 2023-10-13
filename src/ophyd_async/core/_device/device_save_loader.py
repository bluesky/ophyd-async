from enum import Enum
from typing import Any, Dict, Generator, List, Optional, Union

import numpy as np
import yaml
from bluesky import Msg
from yaml.loader import Loader

from ophyd_async.core import Device, SignalRW


def ndarray_representer(dumper: yaml.Dumper, array: np.ndarray) -> yaml.Node:
    return dumper.represent_sequence("tag:yaml.org,2002:seq", array.tolist())


class OphydDumper(yaml.Dumper):
    def represent_data(self, data):
        if isinstance(data, Enum):
            return self.represent_data(data.value)
        return super(OphydDumper, self).represent_data(data)


def get_signal_values(
    signals: Dict[str, SignalRW], ignore: Optional[List[str]] = None
) -> Union[Generator[Dict[str, Any], None, None], Dict[str, Any]]:
    """
    Read the values of SignalRW's, to be used alongside `walk_rw_signals`. Used as part
    of saving a device.
    Parameters
    ----------
        signals : Dict[str, SignalRW]: A dictionary matching the string attribute path
        of a SignalRW to the signal itself

        ignore : List of strings: . A list of string attribute paths to the SignalRW's
        to be ignored.

    Returns
    ----------
        Dict[str, Any]: A dictionary matching the string attribute path of a SignalRW
        to the value of that signal. Ignored attributes are set to None.

    Yields:
        Iterator[Dict[str, Any]]: The Location of a signal

    See Also
    --------
    :func:`ophyd_async.core.walk_rw_signals`
    :func:`ophyd_async.core.save_to_yaml`

    """

    ignore = ignore or []
    selected_signals = {
        key: signal for key, signal in signals.items() if key not in ignore
    }
    selected_values = yield Msg("locate", *selected_signals.values())
    assert selected_values is not None, "No signalRW's were able to be located"
    named_values = {
        key: value["setpoint"] for key, value in zip(selected_signals, selected_values)
    }
    # Ignored values place in with value None so we know which ones were ignored
    named_values.update({key: None for key in ignore})
    return named_values


def walk_rw_signals(
    device: Device, path_prefix: Optional[str] = ""
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
    yaml.add_representer(np.ndarray, ndarray_representer, Dumper=yaml.Dumper)

    if isinstance(phases, dict):
        phases = [phases]

    with open(save_path, "w") as file:
        yaml.dump(phases, file, Dumper=OphydDumper, default_flow_style=None)
