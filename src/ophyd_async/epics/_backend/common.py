from enum import Enum
from typing import Any, Optional, Tuple, Type


def get_supported_enum_class(
    pv: str,
    datatype: Optional[Type[Enum]],
    pv_choices: Tuple[Any, ...],
) -> Type[Enum]:
    if not datatype:
        return Enum("GeneratedChoices", {x or "_": x for x in pv_choices}, type=str)  # type: ignore

    if not issubclass(datatype, Enum):
        raise TypeError(f"{pv} has type Enum not {datatype.__name__}")
    if not issubclass(datatype, str):
        raise TypeError(f"{pv} has type Enum but doesn't inherit from String")
    choices = tuple(v.value for v in datatype)
    if set(choices) != set(pv_choices):
        raise TypeError(
            (
                f"{pv} has choices {pv_choices}, "
                f"which do not match {datatype}, which has {choices}"
            )
        )
    return datatype
