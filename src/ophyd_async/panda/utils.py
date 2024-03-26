from typing import Any, Dict, Sequence, TypedDict


class PVIEntry(TypedDict, total=False):
    d: str
    r: str
    rw: str
    w: str
    x: str


def phase_sorter(panda_signal_values: Dict[str, Any]) -> Sequence[Dict[str, Any]]:
    # Panda has two load phases. If the signal name ends in the string "UNITS",
    # it needs to be loaded first so put in first phase
    phase_1, phase_2 = {}, {}

    for key, value in panda_signal_values.items():
        if key.endswith("units"):
            phase_1[key] = value
        else:
            phase_2[key] = value

    return [phase_1, phase_2]
