from enum import Enum
from typing import Dict, Optional, Tuple, Type, TypedDict

common_meta = {
    "units",
    "precision",
}


class LimitPair(TypedDict):
    high: float | None
    low: float | None

    def __bool__(self) -> bool:
        return self.low is None and self.high is None


class Limits(TypedDict):
    alarm: LimitPair
    control: LimitPair
    display: LimitPair
    warning: LimitPair

    def __bool__(self) -> bool:
        return any(self.alarm, self.control, self.display, self.warning)

from ophyd_async.core.signal_backend import RuntimeEnum


def get_supported_values(
    pv: str,
    datatype: Optional[Type[str]],
    pv_choices: Tuple[str, ...],
) -> Dict[str, str]:
    if not datatype:
        return {x: x or "_" for x in pv_choices}

    if issubclass(datatype, RuntimeEnum):
        if not datatype.choices.issubset(frozenset(pv_choices)):
            raise TypeError(
                f"{pv} has choices {pv_choices}, "
                f"which do not match RuntimeEnum, which has {datatype.choices}"
            )
    elif not issubclass(datatype, str):
        raise TypeError(f"{pv} is type Enum but doesn't inherit from String")
    elif issubclass(datatype, Enum):
        choices = tuple(v.value for v in datatype)
        if set(choices) != set(pv_choices):
            raise TypeError(
                (
                    f"{pv} has choices {pv_choices}, "
                    f"which do not match {datatype}, which has {choices}"
                )
            )
        return {x: datatype(x) for x in pv_choices}
    return {x: x for x in pv_choices}
