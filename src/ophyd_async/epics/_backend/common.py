import inspect
from enum import Enum
from typing import Dict, Optional, Tuple, Type, TypedDict

from ophyd_async.core.signal_backend import SubsetEnum

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


def get_supported_values(
    pv: str,
    datatype: Optional[Type[str]],
    pv_choices: Tuple[str, ...],
) -> Dict[str, str]:
    if inspect.isclass(datatype) and issubclass(datatype, SubsetEnum):
        if not set(datatype.choices).issubset(set(pv_choices)):
            raise TypeError(
                f"{pv} has choices {pv_choices}, "
                f"which is not a superset of {str(datatype)}."
            )
        return {x: x or "_" for x in pv_choices}
    elif inspect.isclass(datatype) and issubclass(datatype, Enum):
        if not issubclass(datatype, str):
            raise TypeError(
                f"{pv} is type Enum but {datatype} does not inherit from String."
            )

        choices = tuple(v.value for v in datatype)
        if set(choices) != set(pv_choices):
            raise TypeError(
                f"{pv} has choices {pv_choices}, "
                f"which do not match {datatype}, which has {choices}."
            )
        return {x: datatype(x) if x else "_" for x in pv_choices}
    elif datatype is None:
        return {x: x or "_" for x in pv_choices}

    raise TypeError(
        f"{pv} has choices {pv_choices}. "
        "Use an Enum or SubsetEnum to represent this."
    )
