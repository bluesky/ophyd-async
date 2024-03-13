from enum import Enum
from typing import Optional, Set, Type


def get_supported_enum_class(
    pv: str,
    datatype: Optional[Type[Enum]],
    pv_choices: Set[str],
) -> Type[Enum]:
    if datatype:
        if not issubclass(datatype, Enum):
            raise TypeError(f"{pv} has type Enum not {datatype.__name__}")
        if not issubclass(datatype, str):
            raise TypeError(f"{pv} has type Enum but doesn't inherit from String")
        choices = tuple(v.value for v in datatype)
        if set(choices).difference(pv_choices):
            raise TypeError(
                f"{pv} has choices {pv_choices} not including all in {choices}"
            )
        return datatype
    else:
        return Enum("GeneratedChoices", {x: x for x in pv_choices}, type=str)
