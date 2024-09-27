from __future__ import annotations

from typing import Annotated, TypeVar, get_origin

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_numpy.helper.annotation import NpArrayPydanticAnnotation

from ophyd_async.core._utils import get_dtype

TableSubclass = TypeVar("TableSubclass", bound="Table")


def _concat(value1, value2):
    if isinstance(value1, np.ndarray):
        return np.concatenate((value1, value2))
    else:
        return value1 + value2


class Table(BaseModel):
    """An abstraction of a Table of str to numpy array."""

    # Allow extra so we can use this as a generic Table
    model_config = ConfigDict(extra="allow")

    @classmethod
    def __init_subclass__(cls):
        # But forbit extra in subclasses so it gets validated
        cls.model_config = ConfigDict(validate_assignment=True, extra="forbid")
        # Change fields to have the correct annotations
        for k, anno in cls.__annotations__.items():
            if get_origin(anno) is np.ndarray:
                dtype = get_dtype(anno)
                new_anno = Annotated[
                    anno,
                    NpArrayPydanticAnnotation.factory(
                        data_type=dtype.type, dimensions=1, strict_data_typing=False
                    ),
                    Field(
                        default_factory=lambda dtype=dtype: np.array([], dtype=dtype)
                    ),
                ]
                cls.__annotations__[k] = new_anno

    @staticmethod
    def row(cls: type[TableSubclass], **kwargs) -> TableSubclass:  # type: ignore
        arrayified_kwargs = {}
        for field_name, field_value in cls.model_fields.items():
            value = kwargs.pop(field_name)
            if field_value.default_factory is None:
                raise ValueError(
                    "`Table` models should have default factories for their "
                    "mutable empty columns."
                )
            default_array = field_value.default_factory()
            if isinstance(default_array, np.ndarray):
                arrayified_kwargs[field_name] = np.array(
                    [value], dtype=default_array.dtype
                )
            elif isinstance(value, str):  # Also covers SubsetEnum
                arrayified_kwargs[field_name] = [value]
            else:
                raise TypeError(
                    "Row column should be numpy arrays or sequence of str | SubsetEnum."
                )
        if kwargs:
            raise TypeError(
                f"Unexpected keyword arguments {kwargs.keys()} for {cls.__name__}."
            )
        return cls(**arrayified_kwargs)

    def __add__(self, right: TableSubclass) -> TableSubclass:
        """Concatenate the arrays in field values."""

        if type(right) is not type(self):
            raise RuntimeError(
                f"{right} is not a `Table`, or is not the same "
                f"type of `Table` as {self}."
            )

        return type(right)(
            **{
                field_name: _concat(
                    getattr(self, field_name), getattr(right, field_name)
                )
                for field_name in self.model_fields
            }
        )

    def __eq__(self, value: object) -> bool:
        return super().__eq__(value)

    def numpy_dtype(self) -> np.dtype:
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
        array = None
        for k, v in self:
            if selection:
                v = v[selection]
            if array is None:
                array = np.empty(v.shape, dtype=self.numpy_dtype(self))
            array[k] = v
        assert array
        return array

    @model_validator(mode="after")
    def validate_arrays(self) -> Table:
        first_length = len(self)
        assert all(
            len(field_value) == first_length for _, field_value in self
        ), "Rows should all be of equal size."
        return self

    def __len__(self) -> int:
        return len(next(iter(self))[1])

    def __getitem__(self, item: int | slice) -> np.ndarray:
        if isinstance(item, int):
            return self.numpy_table(slice(item, item + 1))
        else:
            return self.numpy_table(item)
