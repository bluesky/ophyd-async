from collections.abc import Sequence

from ophyd_async.core import StrictEnum, get_enum_cls


def get_supported_values(
    pv: str,
    datatype: type,
    pv_choices: Sequence[str],
) -> dict[str, str]:
    enum_cls = get_enum_cls(datatype)
    if not enum_cls:
        raise TypeError(f"{datatype} is not an Enum")
    choices = [v.value for v in enum_cls]
    error_msg = f"{pv} has choices {pv_choices}, but {datatype} requested {choices} "
    if issubclass(enum_cls, StrictEnum):
        if set(choices) != set(pv_choices):
            raise TypeError(error_msg + "to be a subset of them.")

    else:
        if not set(choices).issubset(pv_choices):
            raise TypeError(error_msg + "to be strictly equal to them.")

    # Take order from the pv choices
    supported_values = {x: x for x in pv_choices}
    # But override those that we specify via the datatype
    for v in enum_cls:
        supported_values[v.value] = v
    return supported_values
