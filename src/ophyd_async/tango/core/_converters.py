from typing import Any, Generic

import numpy as np
from numpy.typing import NDArray
from tango import DevState

from ophyd_async.core import SignalDatatypeT

from ._utils import DevStateEnum


class TangoConverter(Generic[SignalDatatypeT]):
    def write_value(self, value: Any) -> Any:
        return value

    def value(self, value: Any) -> Any:
        return value


class TangoEnumConverter(TangoConverter):
    def __init__(self, labels: list[str]):
        self._labels = labels

    def write_value(self, value: str):
        if not isinstance(value, str):
            raise TypeError("TangoEnumConverter expects str value")
        return self._labels.index(value)

    def value(self, value: int):
        return self._labels[value]


class TangoEnumArrayConverter(TangoConverter):
    def __init__(self, labels: list[str]):
        self._labels = labels

    def write_value(self, value: NDArray[np.str_]) -> NDArray[np.integer]:
        vfunc = np.vectorize(self._labels.index)
        new_array = vfunc(value)
        return new_array

    def value(self, value: NDArray[np.integer]) -> NDArray[np.str_]:
        vfunc = np.vectorize(self._labels.__getitem__)
        new_array = vfunc(value)
        return new_array


class TangoDevStateConverter(TangoConverter):
    _labels = [e.value for e in DevStateEnum]

    def write_value(self, value: str) -> DevState:
        idx = self._labels.index(value)
        return DevState(idx)

    def value(self, value: DevState) -> str:
        idx = int(value)
        return self._labels[idx]


class TangoDevStateArrayConverter(TangoConverter):
    _labels = [e.value for e in DevStateEnum]

    def _write_convert(self, value):
        return DevState(self._labels.index(value))

    def _convert(self, value):
        return self._labels[int(value)]

    def write_value(self, value: NDArray[np.str_]) -> NDArray[DevState]:
        vfunc = np.vectorize(self._write_convert, otypes=[DevState])
        new_array = vfunc(value)
        return new_array

    def value(self, value: NDArray[DevState]) -> NDArray[np.str_]:
        vfunc = np.vectorize(self._convert)
        new_array = vfunc(value)
        return new_array
