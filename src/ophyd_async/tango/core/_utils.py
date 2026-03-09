import re
from typing import Any, Sequence

import numpy as np

from ophyd_async.core import StrictEnum, Table, Array1D


class DevStateEnum(StrictEnum):
    ON = "ON"
    OFF = "OFF"
    CLOSE = "CLOSE"
    OPEN = "OPEN"
    INSERT = "INSERT"
    EXTRACT = "EXTRACT"
    MOVING = "MOVING"
    STANDBY = "STANDBY"
    FAULT = "FAULT"
    INIT = "INIT"
    RUNNING = "RUNNING"
    ALARM = "ALARM"
    DISABLE = "DISABLE"
    UNKNOWN = "UNKNOWN"


def get_full_attr_trl(device_trl: str, attr_name: str) -> str:
    device_parts = device_trl.split("#", 1)
    # my/device/name#dbase=no splits into my/device/name and
    # dbase=no
    full_trl = device_parts[0] + "/" + attr_name
    if len(device_parts) > 1:
        full_trl += "#" + device_parts[1]
    return full_trl


def get_device_trl_and_attr(name: str):
    # trl can have form:
    #   <protocol://><server:host/>domain/family/member/attr_name<#dbase=no>
    # e.g. tango://127.0.0.1:8888/test/nodb/test#dbase=no
    re_str = (
        r"([\.a-zA-Z0-9_-]*://)?([\.a-zA-Z0-9_-]+:[0-9]+/)?"
        r"([^#/]+/[^#/]+/[^#/]+/)([^#/]+)(#dbase=[a-z]+)?"
    )
    search = re.search(re_str, name)
    if not search:
        raise ValueError(f"Could not parse device and attribute from trl {name}")
    groups = [part if part else "" for part in search.groups()]
    attr = groups.pop(3)  # extract attr name from groups
    groups[2] = groups[2].removesuffix("/")  # remove trailing slash from device name
    device = "".join(groups)
    return device, attr


def try_to_cast_as_float(value: Any) -> float | None:
    """Attempt to cast a value to float, returning None on failure."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


class TangoLongStringTable(Table):
    long: Array1D[np.int32]
    string: Sequence[str]

    def __eq__(self, other):
        if not isinstance(other, TangoLongStringTable):
            return False
        long_equal = np.array_equal(self.long, other.long)
        string_equal = self.string == other.string
        return long_equal and string_equal

class TangoDoubleStringTable(Table):
    double: Array1D[np.float64]
    string: Sequence[str]

    def __eq__(self, other):
        if not isinstance(other, TangoDoubleStringTable):
            return False
        double_equal = np.array_equal(self.double, other.double)
        string_equal = self.string == other.string
        return double_equal and string_equal
