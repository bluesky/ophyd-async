from enum import Enum
from typing import TypeVar, get_args, get_origin

import numpy as np
from pydantic import BaseModel, ConfigDict, model_validator

TableSubclass = TypeVar("TableSubclass", bound="Table")


def _concat(value1, value2):
    if isinstance(value1, np.ndarray):
        return np.concatenate((value1, value2))
    else:
        return value1 + value2


class Table(BaseModel):
    """An abstraction of a Table of str to numpy array."""

    model_config = ConfigDict(validate_assignment=True, strict=False)

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
            elif issubclass(type(value), Enum) and isinstance(value, str):
                arrayified_kwargs[field_name] = [value]
            else:
                raise TypeError(
                    "Row column should be numpy arrays or sequence of string `Enum`."
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

    def numpy_dtype(self) -> np.dtype:
        dtype = []
        for field_name, field_value in self.model_fields.items():
            if np.ndarray in (
                get_origin(field_value.annotation),
                field_value.annotation,
            ):
                dtype.append((field_name, getattr(self, field_name).dtype))
            else:
                enum_type = get_args(field_value.annotation)[0]
                assert issubclass(enum_type, Enum)
                enum_values = [element.value for element in enum_type]
                max_length_in_enum = max(len(value) for value in enum_values)
                dtype.append((field_name, np.dtype(f"<U{max_length_in_enum}")))

        return np.dtype(dtype)

    def numpy_table(self):
        # It would be nice to be able to use np.transpose for this,
        # but it defaults to the largest dtype for everything.
        dtype = self.numpy_dtype()
        transposed_list = [
            np.array(tuple(row), dtype=dtype)
            for row in zip(*self.numpy_columns(), strict=False)
        ]
        transposed = np.array(transposed_list, dtype=dtype)
        return transposed

    def numpy_columns(self) -> list[np.ndarray]:
        """Columns in the table can be lists of string enums or numpy arrays.

        This method returns the columns, converting the string enums to numpy arrays.
        """

        columns = []
        for field_name, field_value in self.model_fields.items():
            if np.ndarray in (
                get_origin(field_value.annotation),
                field_value.annotation,
            ):
                columns.append(getattr(self, field_name))
            else:
                enum_type = get_args(field_value.annotation)[0]
                assert issubclass(enum_type, Enum)
                enum_values = [element.value for element in enum_type]
                max_length_in_enum = max(len(value) for value in enum_values)
                dtype = np.dtype(f"<U{max_length_in_enum}")

                columns.append(
                    np.array(
                        [enum.value for enum in getattr(self, field_name)], dtype=dtype
                    )
                )

        return columns

    @model_validator(mode="after")
    def validate_arrays(self) -> "Table":
        first_length = len(next(iter(self))[1])
        assert all(
            len(field_value) == first_length for _, field_value in self
        ), "Rows should all be of equal size."

        if not all(
            # Checks if the values are numpy subtypes if the array is a numpy array,
            # or if the value is a string enum.
            np.issubdtype(getattr(self, field_name).dtype, default_array.dtype)
            if isinstance(
                default_array := self.model_fields[field_name].default_factory(),  # type: ignore
                np.ndarray,
            )
            else issubclass(get_args(field_value.annotation)[0], Enum)
            for field_name, field_value in self.model_fields.items()
        ):
            raise ValueError(
                f"Cannot construct a `{type(self).__name__}`, "
                "some rows have incorrect types."
            )

        return self
