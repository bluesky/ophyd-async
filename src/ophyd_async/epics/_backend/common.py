from enum import Enum
from typing import Any, Optional, Tuple, Type


def get_supported_enum_class(
    pv: str,
    datatype: Optional[Type[Enum]],
    pv_choices: Tuple[Any, ...],
    read_datatype: Optional[Type[str]] = None,
) -> Type[Enum]:
    if not datatype:
        return Enum("GeneratedChoices", {x or "_": x for x in pv_choices}, type=str)  # type: ignore

    if not issubclass(datatype, Enum):
        raise TypeError(f"{pv} has type Enum not {datatype.__name__}")
    if not issubclass(datatype, str):
        raise TypeError(f"{pv} has type Enum but doesn't inherit from String")
    choices = tuple(v.value for v in datatype)
    if any(choice not in pv_choices for choice in choices):
        raise TypeError(
            (
                f"{pv} has choices {pv_choices}, "
                f"which do not match {datatype}, which has {choices}"
            )
        )
    if any(choice not in choices for choice in pv_choices):
        if read_datatype:
            return Enum("GeneratedChoices", {x or "_": x for x in pv_choices}, type=str)  # type: ignore
        else:
            raise TypeError(
                (
                    f"{pv} has choices {pv_choices}, "
                    f"which do not match {datatype}, which has {choices}"
                )
            )
    return datatype
