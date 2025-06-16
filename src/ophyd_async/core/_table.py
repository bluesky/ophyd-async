from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Annotated, Any, TypeVar, get_origin, get_type_hints

import numpy as np
from pydantic import ConfigDict, Field, model_validator
from pydantic_numpy.helper.annotation import NpArrayPydanticAnnotation

from ._utils import ConfinedModel, get_dtype

TableSubclass = TypeVar("TableSubclass", bound="Table")


def _concat(value1, value2):
    if isinstance(value1, np.ndarray):
        return np.concatenate((value1, value2))
    else:
        return value1 + value2


def _make_default_factory(dtype: np.dtype) -> Callable[[], np.ndarray]:
    def numpy_array_default_factory() -> np.ndarray:
        return np.array([], dtype)

    return numpy_array_default_factory


class Table(ConfinedModel):
    """An abstraction of a Table where each field is a column.

    For example:
    ```python
    >>> from ophyd_async.core import Table, Array1D
    >>> import numpy as np
    >>> from collections.abc import Sequence
    >>> class MyTable(Table):
    ...     a: Array1D[np.int8]
    ...     b: Sequence[str]
    ...
    >>> t = MyTable(a=[1, 2], b=["x", "y"])
    >>> len(t)  # the length is the number of rows
    2
    >>> t2 = t + t  # adding tables together concatenates them
    >>> t2.a
    array([1, 2, 1, 2], dtype=int8)
    >>> t2.b
    ['x', 'y', 'x', 'y']
    >>> t2[1]  # slice a row
    array([(2, b'y')], dtype=[('a', 'i1'), ('b', 'S40')])

    ```
    """

    # You can use Table in 2 ways:
    # 1. Table(**whatever_pva_gives_us) when pvi adds a Signal to a Device that is not
    #    type hinted
    # 2. MyTable(**whatever_pva_gives_us) where the Signal is type hinted
    #
    # For 1 we want extra="allow" so it is passed through as is. There are no base class
    # fields, only "extra" fields, so they must be allowed. For 2 we want extra="forbid"
    # so it is strictly checked against the BaseModel we are supplied.
    model_config = ConfigDict(extra="allow")

    # Add an init method to match the above model config, otherwise the type
    # checker will not think we can pass arbitrary kwargs into the base class init...
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    @classmethod
    def __init_subclass__(cls):
        # ...but forbid extra in subclasses so it gets validated
        cls.model_config = ConfigDict(validate_assignment=True, extra="forbid")
        # Change fields to have the correct annotations
        # TODO: refactor so we don't need this to break circular imports
        from ._signal_backend import Array1D

        for k, anno in get_type_hints(cls, localns={"Array1D": Array1D}).items():
            if get_origin(anno) is np.ndarray:
                dtype = get_dtype(anno)
                new_anno = Annotated[
                    anno,
                    NpArrayPydanticAnnotation.factory(
                        data_type=dtype.type, dimensions=1, strict_data_typing=False
                    ),
                    Field(default_factory=_make_default_factory(dtype)),
                ]
            elif get_origin(anno) is Sequence:
                new_anno = Annotated[anno, Field(default_factory=list)]
            else:
                raise TypeError(f"Cannot use annotation {anno} in a Table")
            cls.__annotations__[k] = new_anno

    def __add__(self, right: TableSubclass) -> TableSubclass:
        """Concatenate the arrays in field values."""
        cls = type(right)
        if type(self) is not cls:
            raise RuntimeError(
                f"{right} is not a `Table`, or is not the same "
                f"type of `Table` as {self}."
            )

        return cls(
            **{
                field_name: _concat(
                    getattr(self, field_name), getattr(right, field_name)
                )
                for field_name in cls.model_fields
            }
        )

    def numpy_dtype(self) -> np.dtype:
        """Return a numpy dtype for a single row."""
        dtype = []
        for k, v in self:
            if isinstance(v, np.ndarray):
                dtype.append((k, v.dtype))
            else:
                # TODO: use np.dtypes.StringDType when we can use in structured arrays
                # https://github.com/numpy/numpy/issues/25693
                dtype.append((k, np.dtype("S40")))
        return np.dtype(dtype)

    def numpy_table(self, selection: slice | None = None) -> np.ndarray:
        """Return a numpy array of the whole table."""
        array = None
        for k, v in self:
            if selection:
                v = v[selection]
            if array is None:
                array = np.empty(v.shape, dtype=self.numpy_dtype())
            array[k] = v  # type: ignore
        if array is None:
            msg = "No arrays found in table"
            raise ValueError(msg)
        return array

    @model_validator(mode="before")
    @classmethod
    def _validate_array_dtypes(cls, data: Any) -> Any:
        # Validates that array datatypes given in the table are of the
        # correct format.
        if isinstance(data, dict):
            data_dict = data
        elif isinstance(data, Table):
            data_dict = data.model_dump()
        else:
            raise AssertionError(f"Cannot construct Table from {data}")
        for field_name, field_value in cls.model_fields.items():
            if (
                get_origin(field_value.annotation) is np.ndarray
                and field_value.annotation
                and field_name in data_dict
            ):
                data_value = data_dict[field_name]
                expected_dtype = get_dtype(field_value.annotation)
                # Convert to correct dtype, but only if we don't lose precision
                # as a result
                cast_value = np.array(data_value).astype(expected_dtype)
                if not np.array_equal(data_value, cast_value):
                    msg = (
                        f"{field_name}: Cannot cast {data_value} to {expected_dtype} "
                        "without losing precision"
                    )
                    raise ValueError(msg)
                data_dict[field_name] = cast_value
        return data_dict

    @model_validator(mode="after")
    def _validate_lengths(self) -> Table:
        lengths: dict[int, set[str]] = {}
        for field_name, field_value in self:
            lengths.setdefault(len(field_value), set()).add(field_name)
        if len(lengths) > 1:
            msg = f"Columns should be same length, got {lengths=}"
            raise ValueError(msg)
        return self

    def __len__(self) -> int:
        return len(next(iter(self))[1])

    def __getitem__(self, item: int | slice) -> np.ndarray:
        if isinstance(item, int):
            return self.numpy_table(slice(item, item + 1))
        else:
            return self.numpy_table(item)
