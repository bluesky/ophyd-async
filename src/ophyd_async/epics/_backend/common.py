from dataclasses import dataclass
from enum import Enum
from typing import Dict, Generic, Optional, Tuple, Type

from ophyd_async.core import T

common_meta = {
    "units",
    "precision",
}


@dataclass
class LimitPair(Generic[T]):
    high: T | None = None
    low: T | None = None


@dataclass
class Limits(Generic[T]):
    control: LimitPair[T]
    display: LimitPair[T]
    warning: LimitPair[T]
    alarm: LimitPair[T]


def get_supported_values(
    pv: str,
    datatype: Optional[Type[str]],
    pv_choices: Tuple[str, ...],
) -> Dict[str, str]:
    if not datatype:
        return {x: x or "_" for x in pv_choices}

    if not issubclass(datatype, str):
        raise TypeError(f"{pv} is type Enum but doesn't inherit from String")
    if issubclass(datatype, Enum):
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
