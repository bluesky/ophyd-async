from typing import Any, Generic

import numpy as np
from numpy.typing import NDArray

from ophyd_async.core import (
    SignalDatatypeT,
)
from tango import (
    DevState,
)

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


class TangoEnumSpectrumConverter(TangoConverter):
    def __init__(self, labels: list[str]):
        self._labels = labels

    def write_value(self, value: NDArray[np.str_]) -> NDArray[np.integer]:
        # should return array of ints
        return np.array([self._labels.index(v) for v in value])

    def value(self, value) -> NDArray[np.str_]:
        # should return array of strs
        return np.array([self._labels[v] for v in value])


class TangoEnumImageConverter(TangoConverter):
    def __init__(self, labels: list[str]):
        self._labels = labels

    def write_value(self, value: NDArray[np.str_]) -> NDArray[np.integer]:
        return np.vstack([[self._labels.index(v) for v in row] for row in value])

    def value(self, value) -> NDArray[np.str_]:
        return np.vstack([[self._labels[v] for v in row] for row in value])


class TangoDevStateConverter(TangoConverter):
    _labels = [e.value for e in DevStateEnum]

    def write_value(self, value: str) -> DevState:
        idx = self._labels.index(value)
        return DevState(idx)

    def value(self, value: DevState) -> str:
        idx = int(value)
        return self._labels[idx]


class TangoDevStateSpectrumConverter(TangoConverter):
    _labels = [e.value for e in DevStateEnum]

    def write_value(self, value: NDArray[np.str_]) -> NDArray[DevState]:
        return np.array(
            [DevState(self._labels.index(v)) for v in value], dtype=DevState
        )

    def value(self, value: NDArray[DevState]) -> NDArray[np.str_]:
        result = np.array([self._labels[int(v)] for v in value])
        return result


class TangoDevStateImageConverter(TangoConverter):
    _labels = [e.value for e in DevStateEnum]

    def write_value(self, value: NDArray[np.str_]) -> NDArray[DevState]:
        result = np.vstack(
            [
                np.array([DevState(self._labels.index(v)) for v in row], dtype=DevState)
                for row in value
            ],
        )

        return result

    def value(self, value: NDArray[DevState]) -> NDArray[np.str_]:
        return np.vstack([[self._labels[int(v)] for v in row] for row in value])
