from collections.abc import Callable, Generator, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import yaml
from bluesky.plan_stubs import abs_set, wait
from bluesky.protocols import Location
from bluesky.utils import Msg
from pydantic import BaseModel

from ._device import Device
from ._signal import SignalRW


def ndarray_representer(dumper: yaml.Dumper, array: npt.NDArray[Any]) -> yaml.Node:
    return dumper.represent_sequence(
        "tag:yaml.org,2002:seq", array.tolist(), flow_style=True
    )


def pydantic_model_abstraction_representer(
    dumper: yaml.Dumper, model: BaseModel
) -> yaml.Node:
    return dumper.represent_data(model.model_dump(mode="python"))


class OphydDumper(yaml.Dumper):
    def represent_data(self, data: Any) -> Any:
        if isinstance(data, Enum):
            return self.represent_data(data.value)
        return super().represent_data(data)


def get_signal_values(
    signals: dict[str, SignalRW[Any]], ignore: list[str] | None = None
) -> Generator[Msg, Sequence[Location[Any]], dict[str, Any]]:
    """Get signal values in bulk.

    Used as part of saving the signals of a device to a yaml file.

    Parameters
    ----------
    signals : Dict[str, SignalRW]
        Dictionary with pv names and matching SignalRW values. Often the direct result
        of :func:`walk_rw_signals`.

    ignore : Optional[List[str]]
        Optional list of PVs that should be ignored.

    Returns
    -------
    Dict[str, Any]
        A dictionary containing pv names and their associated values. Ignored pvs are
        set to None.

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
        key: value["setpoint"]
        for key, value in zip(selected_signals, selected_values, strict=False)
    }
    # Ignored values place in with value None so we know which ones were ignored
    named_values.update({key: None for key in ignore})
    return named_values


def walk_rw_signals(
    device: Device, path_prefix: str | None = ""
) -> dict[str, SignalRW[Any]]:
    """Retrieve all SignalRWs from a device.

    Stores retrieved signals with their dotted attribute paths in a dictionary. Used as
    part of saving and loading a device.

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

    signals: dict[str, SignalRW[Any]] = {}
    for attr_name, attr in device.children():
        dot_path = f"{path_prefix}{attr_name}"
        if type(attr) is SignalRW:
            signals[dot_path] = attr
        attr_signals = walk_rw_signals(attr, path_prefix=dot_path + ".")
        signals.update(attr_signals)
    return signals


def save_to_yaml(phases: Sequence[dict[str, Any]], save_path: str | Path) -> None:
    """Plan which serialises a phase or set of phases of SignalRWs to a yaml file.

    Parameters
    ----------
    phases : dict or list of dicts
        The values to save. Each item in the list is a seperate phase used when loading
        a device. In general this variable be the return value of `get_signal_values`.

    save_path : str
        Path of the yaml file to write to

    See Also
    --------
    :func:`ophyd_async.core.walk_rw_signals`
    :func:`ophyd_async.core.get_signal_values`
    :func:`ophyd_async.core.load_from_yaml`
    """

    yaml.add_representer(np.ndarray, ndarray_representer, Dumper=yaml.Dumper)
    yaml.add_multi_representer(
        BaseModel,
        pydantic_model_abstraction_representer,
        Dumper=yaml.Dumper,
    )

    with open(save_path, "w") as file:
        yaml.dump(phases, file, Dumper=OphydDumper, default_flow_style=False)


def load_from_yaml(save_path: str) -> Sequence[dict[str, Any]]:
    """Plan that returns a list of dicts with saved signal values from a yaml file.

    Parameters
    ----------
    save_path : str
        Path of the yaml file to load from

    See Also
    --------
    :func:`ophyd_async.core.save_to_yaml`
    :func:`ophyd_async.core.set_signal_values`
    """
    with open(save_path) as file:
        return yaml.full_load(file)


def set_signal_values(
    signals: dict[str, SignalRW[Any]], values: Sequence[dict[str, Any]]
) -> Generator[Msg, None, None]:
    """Maps signals from a yaml file into device signals.

    ``values`` contains signal values in phases, which are loaded in sequentially
    into the provided signals, to ensure signals are set in the correct order.

    Parameters
    ----------
    signals : Dict[str, SignalRW[Any]]
        Dictionary of named signals to be updated if value found in values argument.
        Can be the output of :func:`walk_rw_signals()` for a device.

    values : Sequence[Dict[str, Any]]
        List of dictionaries of signal name and value pairs, if a signal matches
        the name of one in the signals argument, sets the signal to that value.
        The groups of signals are loaded in their list order.
        Can be the output of :func:`load_from_yaml()` for a yaml file.

    See Also
    --------
    :func:`ophyd_async.core.load_from_yaml`
    :func:`ophyd_async.core.walk_rw_signals`
    """
    # For each phase, set all the signals,
    # load them to the correct value and wait for the load to complete
    for phase_number, phase in enumerate(values):
        # Key is signal name
        for key, value in phase.items():
            # Skip ignored values
            if value is None:
                continue

            if key in signals:
                yield from abs_set(
                    signals[key], value, group=f"load-phase{phase_number}"
                )

        yield from wait(f"load-phase{phase_number}")


def load_device(device: Device, path: str):
    """Plan which loads PVs from a yaml file into a device.

    Parameters
    ----------
    device: Device
        The device to load PVs into
    path: str
        Path of the yaml file to load

    See Also
    --------
    :func:`ophyd_async.core.save_device`
    """
    values = load_from_yaml(path)
    signals_to_set = walk_rw_signals(device)
    yield from set_signal_values(signals_to_set, values)


def all_at_once(values: dict[str, Any]) -> Sequence[dict[str, Any]]:
    """Sort all the values into a single phase so they are set all at once"""
    return [values]


def save_device(
    device: Device,
    path: str,
    sorter: Callable[[dict[str, Any]], Sequence[dict[str, Any]]] = all_at_once,
    ignore: list[str] | None = None,
):
    """Plan that saves the state of all PV's on a device using a sorter.

    The default sorter assumes all saved PVs can be loaded at once, and therefore
    can be saved at one time, i.e. all PVs will appear on one list in the
    resulting yaml file.

    This can be a problem, because when the yaml is ingested with
    :func:`ophyd_async.core.load_device`, it will set all of those PVs at once.
    However, some PV's need to be set before others - this is device specific.

    Therefore, users should consider the order of device loading and write their
    own sorter algorithms accordingly.

    See :func:`ophyd_async.fastcs.panda.phase_sorter` for a valid implementation of the
    sorter.

    Parameters
    ----------
    device : Device
        The device whose PVs should be saved.

    path : str
        The path where the resulting yaml should be saved to

    sorter : Callable[[Dict[str, Any]], Sequence[Dict[str, Any]]]

    ignore : Optional[List[str]]

    See Also
    --------
    :func:`ophyd_async.core.load_device`
    """
    values = yield from get_signal_values(walk_rw_signals(device), ignore=ignore)
    save_to_yaml(sorter(values), path)
