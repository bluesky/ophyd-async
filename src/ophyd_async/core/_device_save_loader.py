import warnings
from collections.abc import Generator, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import yaml
from bluesky.plan_stubs import abs_set, wait
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


def enum_representer(dumper: yaml.Dumper, enum: Enum) -> yaml.Node:
    return dumper.represent_data(enum.value)


def save_to_yaml(data: dict[str, Any], save_path: str | Path) -> None:
    """Plan which serialises a phase or set of phases of SignalRWs to a yaml file.

    Parameters
    ----------
    data : dict
        The dotted attribute path and value to save.

    save_path : str
        Path of the yaml file to write to

    See Also
    --------
    :func:`ophyd_async.core.settings_to_yaml`
    :func:`ophyd_async.core.load_from_yaml`
    """

    yaml.add_representer(np.ndarray, ndarray_representer, Dumper=yaml.Dumper)
    yaml.add_multi_representer(
        BaseModel,
        pydantic_model_abstraction_representer,
        Dumper=yaml.Dumper,
    )
    yaml.add_multi_representer(Enum, enum_representer, Dumper=yaml.Dumper)

    with open(save_path, "w") as file:
        yaml.dump(data, file)


def load_from_yaml(save_path: str | Path) -> dict[str, Any]:
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
        data = yaml.full_load(file)
    if isinstance(data, list):
        warnings.warn(
            DeprecationWarning(
                f"Found old save file. Re-save your yaml settings file {save_path}"
                " using ophyd.core.settings_to_yaml()"
            ),
            stacklevel=2,
        )
        merge = {}
        for d in data:
            merge.update(d)
        return merge
    return data


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
