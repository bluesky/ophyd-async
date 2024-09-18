from typing import TypeVar

import numpy as np
from pydantic import BaseModel, ConfigDict, model_validator

TableSubclass = TypeVar("TableSubclass", bound="Table")


class Table(BaseModel):
    """An abstraction of a Table of str to numpy array."""

    model_config = ConfigDict(validate_assignment=True, strict=False)

    @staticmethod
    def row(cls: type[TableSubclass], **kwargs) -> TableSubclass:  # type: ignore
        arrayified_kwargs = {
            field_name: np.concatenate(
                (
                    (default_arr := field_value.default_factory()),  # type: ignore
                    np.array([kwargs[field_name]], dtype=default_arr.dtype),
                )
            )
            for field_name, field_value in cls.model_fields.items()
        }
        return cls(**arrayified_kwargs)

    def __add__(self, right: TableSubclass) -> TableSubclass:
        """Concatenate the arrays in field values."""

        assert type(right) is type(self), (
            f"{right} is not a `Table`, or is not the same "
            f"type of `Table` as {self}."
        )

        return type(right)(
            **{
                field_name: np.concatenate(
                    (getattr(self, field_name), getattr(right, field_name))
                )
                for field_name in self.model_fields
            }
        )

    @model_validator(mode="after")
    def validate_arrays(self) -> "Table":
        first_length = len(next(iter(self))[1])
        assert all(
            len(field_value) == first_length for _, field_value in self
        ), "Rows should all be of equal size."

        if not all(
            np.issubdtype(
                self.model_fields[field_name].default_factory().dtype,  # type: ignore
                field_value.dtype,
            )
            for field_name, field_value in self
        ):
            raise ValueError(
                f"Cannot construct a `{type(self).__name__}`, "
                "some rows have incorrect types."
            )

        return self
