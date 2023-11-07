from typing import List, Optional

from ophyd_async.core import (
    get_signal_values,
    load_from_yaml,
    save_to_yaml,
    set_signal_values,
    walk_rw_signals,
)
from ophyd_async.panda import PandA


def _get_panda_phases(panda: PandA, ignore: Optional[List[str]] = None):
    # Panda has two load phases. If the signal name ends in the string "UNITS", it needs to be loaded first so put in first phase
    signalRW_and_value = yield from get_signal_values(walk_rw_signals(panda), ignore)
    phase_1 = {}
    phase_2 = {}
    for signal_name in signalRW_and_value.keys():
        if signal_name[-5:] == "units":
            phase_1[signal_name] = signalRW_and_value[signal_name]
        else:
            phase_2[signal_name] = signalRW_and_value[signal_name]

    return [phase_1, phase_2]


def save_panda(panda: PandA, path: str, ignore: Optional[List[str]] = None):
    """
    Saves all the panda PV's to a yaml file, ignoring any PV's in the `ignore` parameter
    """
    phases = yield from _get_panda_phases(panda, ignore=ignore)
    save_to_yaml(phases, path)


def load_panda(panda: PandA, path: str):
    """
    Sets all PV's to a PandA using a previously saved configuration
    """
    values = load_from_yaml(path)
    signals_to_set = walk_rw_signals(panda)
    yield from set_signal_values(signals_to_set, values)
