from typing import List, Optional

from ophyd_async.core import get_signal_values, save_to_yaml, walk_rw_signals
from ophyd_async.panda import PandA


def _get_panda_phases(panda: PandA, ignore: Optional[List[str]] = None):
    # Panda has two load phases. If the signal name ends in the string "UNITS",
    # it needs to be loaded first so put in first phase
    signals = walk_rw_signals(panda)
    phase_2 = yield from get_signal_values(signals, ignore=ignore)
    phase_1 = {n: phase_2.pop(n) for n in list(phase_2) if n.endswith("units")}
    return [phase_1, phase_2]


def save_panda(panda: PandA, path: str, ignore: Optional[List[str]] = None):
    """
    Saves all the panda PV's to a yaml file, ignoring any PV's in the `ignore`
    parameter
    """
    phases = yield from _get_panda_phases(panda, ignore=ignore)
    save_to_yaml(phases, path)
