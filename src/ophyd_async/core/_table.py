from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, TypeVar, get_origin

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_numpy.helper.annotation import NpArrayPydanticAnnotation

from ._utils import get_dtype

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
            elif get_origin(anno) is Sequence:
                new_anno = Annotated[anno, Field(default_factory=list)]
            else:
                raise TypeError(f"Cannot use annotation {anno} in a Table")
            cls.__annotations__[k] = new_anno

    def __add__(self, right: TableSubclass) -> TableSubclass:
        """Concatenate the arrays in field values."""

        if type(right) is not type(self):
            raise RuntimeError(
                f"{right} is not a `Table`, or is not the same "
                f"type of `Table` as {self}."
            )

        return type(right)(**{
            field_name: _concat(getattr(self, field_name), getattr(right, field_name))
            for field_name in self.model_fields
        })

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
                array = np.empty(v.shape, dtype=self.numpy_dtype())
            array[k] = v
        assert array is not None
        return array

    # TODO: would like to do this validation, but too strict for CA which returns
    # bool arrays as uint8 arrays
    # @model_validator(mode="before")
    # @classmethod
    # def validate_array_dtypes(cls, data: Any) -> Any:
    #     if isinstance(data, dict):
    #         data_dict = data
    #     elif isinstance(data, Table):
    #         data_dict = data.model_dump()
    #     else:
    #         assert False, f"Cannot construct Table from {data}"
    #     for field_name, field_value in cls.model_fields.items():
    #         if get_origin(field_value.annotation) is np.ndarray:
    #             data_value = data_dict.get(field_name, None)
    #             if isinstance(data_value, np.ndarray) and field_value.annotation:
    #                 expected_dtype = get_dtype(field_value.annotation)
    #                 assert data_value.dtype == expected_dtype, (
    #                     f"{field_name}: expected dtype {expected_dtype}, "
    #                     f"got {data_value.dtype}"
    #                 )
    #     return data

    @model_validator(mode="after")
    def validate_lengths(self) -> Table:
        lengths: dict[int, set[str]] = {}
        for field_name, field_value in self:
            lengths.setdefault(len(field_value), set()).add(field_name)
        assert len(lengths) <= 1, f"Columns should be same length, got {lengths=}"
        return self

    def __len__(self) -> int:
        return len(next(iter(self))[1])

    def __getitem__(self, item: int | slice) -> np.ndarray:
        if isinstance(item, int):
            return self.numpy_table(slice(item, item + 1))
        else:
            return self.numpy_table(item)
