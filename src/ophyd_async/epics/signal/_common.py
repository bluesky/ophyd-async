import inspect
from enum import Enum

from typing_extensions import TypedDict

from ophyd_async.core import RuntimeSubsetEnum

common_meta = {
    "units",
    "precision",
}


class LimitPair(TypedDict):
    high: float | None
    low: float | None


class Limits(TypedDict):
    alarm: LimitPair
    control: LimitPair
    display: LimitPair
    warning: LimitPair


def get_supported_values(
    pv: str,
    datatype: type[str] | None,
    pv_choices: tuple[str, ...],
) -> dict[str, str]:
    if inspect.isclass(datatype) and issubclass(datatype, RuntimeSubsetEnum):
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
    elif datatype is None or datatype is str:
        return {x: x or "_" for x in pv_choices}

    raise TypeError(
        f"{pv} has choices {pv_choices}. "
        "Use an Enum or SubsetEnum to represent this."
    )
