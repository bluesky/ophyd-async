from enum import Enum
from typing import Any, Optional, Tuple, Type


def get_supported_values(
    pv: str,
    datatype: Optional[Type[Enum]],
    pv_choices: Tuple[Any, ...],
) -> Tuple[Any, ...]:
    if not datatype:
        return tuple(x or "_" for x in pv_choices)

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
    return pv_choices
