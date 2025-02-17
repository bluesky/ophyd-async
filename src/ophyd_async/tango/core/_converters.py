from typing import Any, Generic

import numpy as np

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


class TangoEnumSpectrumConverter(TangoEnumConverter):
    def write_value(self, value: np.ndarray[Any, str]):
        # should return array of ints
        return np.array([self._labels.index(v) for v in value])

    def value(self, value: np.ndarray[Any, int]):
        # should return array of strs
        return np.array([self._labels[v] for v in value])


class TangoEnumImageConverter(TangoEnumConverter):
    def write_value(self, value: np.ndarray[Any, str]):
        # should return array of ints
        return np.vstack([[self._labels.index(v) for v in row] for row in value])

    def value(self, value: np.ndarray[Any, int]):
        # should return array of strs
        return np.vstack([[self._labels[v] for v in row] for row in value])


class TangoDevStateConverter(TangoConverter):
    _labels = [e.value for e in DevStateEnum]

    def write_value(self, value: Any) -> Any:
        idx = self._labels.index(value)
        return DevState(idx)

    def value(self, value: DevState) -> Any:
        idx = int(value)
        return self._labels[idx]


class TangoDevStateSpectrumConverter(TangoDevStateConverter):
    def write_value(self, value):
        # should return array of tango `DevState`s
        return np.array(
            [DevState(self._labels.index(v)) for v in value], dtype=DevState
        )

    def value(self, value):
        # should return array of strs
        result = np.array([self._labels[int(v)] for v in value])
        return result


class TangoDevStateImageConverter(TangoDevStateConverter):
    def write_value(self, value):
        # should return array of tango `DevState`s
        result = np.vstack(
            [
                np.array([DevState(self._labels.index(v)) for v in row], dtype=DevState)
                for row in value
            ],
        )

        return result

    def value(self, value):
        # should return array of strs
        return np.vstack([[self._labels[int(v)] for v in row] for row in value])
