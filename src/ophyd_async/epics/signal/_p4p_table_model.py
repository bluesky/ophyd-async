import numpy as np
from pydantic import BaseModel, ConfigDict, model_validator


class PvaTable(BaseModel):
    """An abstraction of a PVA Table of str to numpy array."""

    model_config = ConfigDict(validate_assignment=True, strict=False)

    @classmethod
    def row(cls, sub_cls, **kwargs) -> "PvaTable":
        arrayified_kwargs = {
            field_name: np.concatenate(
                (
                    (default_arr := field_value.default_factory()),
                    np.array([kwargs[field_name]], dtype=default_arr.dtype),
                )
            )
            for field_name, field_value in sub_cls.model_fields.items()
        }
        return sub_cls(**arrayified_kwargs)

    def __add__(self, right: "PvaTable") -> "PvaTable":
        """Concatenate the arrays in field values."""

        assert isinstance(right, type(self)), (
            f"{right} is not a `PvaTable`, or is not the same "
            f"type of `PvaTable` as {self}."
        )

        return type(self)(
            **{
                field_name: np.concatenate(
                    (getattr(self, field_name), getattr(right, field_name))
                )
                for field_name in self.model_fields
            }
        )

    @model_validator(mode="after")
    def validate_arrays(self) -> "PvaTable":
        first_length = len(next(iter(self))[1])
        assert all(
            len(field_value) == first_length for _, field_value in self
        ), "Rows should all be of equal size."

        assert 0 <= first_length < 4096, f"Length {first_length} not in range."

        if not all(
            np.issubdtype(
                self.model_fields[field_name].default_factory().dtype, field_value.dtype
            )
            for field_name, field_value in self
        ):
            raise ValueError(
                f"Cannot construct a `{type(self).__name__}`, "
                "some rows have incorrect types."
            )

        return self
