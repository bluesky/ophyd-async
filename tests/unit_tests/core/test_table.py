from collections.abc import Sequence
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from ophyd_async.core import Array1D, Table


class MyTable(Table):
    bool: Array1D[np.bool_]
    uint: Array1D[np.uint32]
    str: Sequence[str]


@pytest.mark.parametrize(
    ["kwargs", "error_msg"],
    [
        (
            {"bool": [3, 4], "uint": [3, 4], "str": ["", ""]},
            "bool: Cannot cast [3, 4] to bool without losing precision",
        ),
        (
            {"bool": np.array([1], dtype=np.uint8), "uint": [-3], "str": [""]},
            "uint: Cannot cast [-3] to uint32 without losing precision",
        ),
        (
            {"bool": [0], "uint": np.array([1.8], dtype=np.float64), "str": [""]},
            "uint: Cannot cast [1.8] to uint32 without losing precision",
        ),
        (
            {"bool": [0, 1], "uint": [3, 4], "str": [44, ""]},
            "Input should be a valid string [type=string_type, input_value=44,",
        ),
        (
            {"bool": [0, 1], "uint": [[3], [4]], "str": ["", ""]},
            "Array 2-dimensional; the target dimensions is 1",
        ),
    ],
)
def test_table_wrong_types(kwargs, error_msg):
    with pytest.raises(ValidationError) as cm:
        MyTable(**kwargs)
    assert error_msg in str(cm.value)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"bool": np.array([1], dtype=np.uint8), "uint": [3], "str": ["a"]},
        {
            "bool": np.array([False], dtype=np.bool_),
            "uint": np.array([1], dtype=np.float64),
            "str": ["b"],
        },
    ],
)
def test_table_coerces(kwargs):
    t = MyTable(**kwargs)
    for k, v in t:
        assert v == pytest.approx(kwargs[k])
    assert t == pytest.approx(t)


def test_validate_array_dtypes():
    class TestTable(Table):
        int_array: np.ndarray[Any, np.dtype[np.int32]]

    with pytest.raises(ValueError, match=r"Cannot cast .* without losing precision"):
        TestTable(int_array=[1.5, 2.5])  # type: ignore

    table = TestTable(int_array=[1, 2])  # type: ignore
    assert table.int_array.dtype == np.dtype(np.int32)

    table = TestTable(int_array=[])  # type: ignore
    assert table.int_array.dtype == np.dtype(np.int32)
