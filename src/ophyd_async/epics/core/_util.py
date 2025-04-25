from collections.abc import Sequence
from typing import Any, get_args, get_origin

import numpy as np

from ophyd_async.core import (
    SignalBackend,
    SignalDatatypeT,
    StrictEnum,
    SubsetEnum,
    SupersetEnum,
    get_dtype,
    get_enum_cls,
)


def get_pv_basename_and_field(pv: str) -> tuple[str, str | None]:
    """Split PV into record name and field."""
    if "." in pv:
        record, field = pv.split(".", maxsplit=1)
    else:
        record, field = pv, None
    return (record, field)


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
            raise TypeError(error_msg + "to be strictly equal to them.")
    elif issubclass(enum_cls, SubsetEnum):
        if not set(choices).issubset(pv_choices):
            raise TypeError(error_msg + "to be a subset of them.")
    elif issubclass(enum_cls, SupersetEnum):
        if (
            not set(pv_choices).issubset(choices) or
            len(set(choices).intersection(pv_choices)) == 0
        ):
            raise TypeError(
                error_msg + ". There should be no extras and at least one match."
            )

    # Take order from the pv choices
    supported_values = {x: x for x in pv_choices}
    # But override those that we specify via the datatype
    for v in enum_cls:
        supported_values[v.value] = v

    if issubclass(enum_cls, SupersetEnum):
        # Convert to sets and use symmetric difference
        missing_choices = list(set(pv_choices) ^ set(choices))
        # Remove the missing choices from pv from supported values
        for m in missing_choices:
            del supported_values[m]
    return supported_values


def format_datatype(datatype: Any) -> str:
    if get_origin(datatype) is np.ndarray and get_args(datatype):
        dtype = get_dtype(datatype)
        return f"Array1D[np.{dtype.name}]"
    elif get_origin(datatype) is Sequence:
        return f"Sequence[{get_args(datatype)[0].__name__}]"
    elif isinstance(datatype, type):
        return datatype.__name__
    else:
        return str(datatype)


class EpicsSignalBackend(SignalBackend[SignalDatatypeT]):
    def __init__(
        self,
        datatype: type[SignalDatatypeT] | None,
        read_pv: str = "",
        write_pv: str = "",
    ):
        self.read_pv = read_pv
        self.write_pv = write_pv
        super().__init__(datatype)
