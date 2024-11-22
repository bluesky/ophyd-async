import asyncio
from dataclasses import dataclass
from typing import TypeVar

import numpy as np
import pytest

from ophyd_async.core import (
    Array1D,
    AsyncStatus,
    DerivedBackend,
    Device,
    Transform,
    TransformArgument,
    soft_signal_rw,
)


async def test_transform_argument_cls_inference():
    class Raw(TransformArgument[float]): ...

    class Derived(TransformArgument[float]): ...

    with pytest.raises(
        TypeError,
        match=(
            "Too few arguments for "
            "<class 'ophyd_async.core._derived_signal.Transform'>; "
            "actual 2, expected at least 3"
        ),
    ):

        class SomeTransform1(Transform[Raw, Derived]): ...  # type: ignore

    with pytest.raises(
        TypeError,
        match=(
            "Transform classes must be defined with Raw, Derived, "
            "and Parameter args."
        ),
    ):

        class SomeTransform2(Transform): ...

    class Parameters(TransformArgument[float]): ...

    class SomeTransform(Transform[Raw, Derived, Parameters]): ...

    assert SomeTransform.raw_cls is Raw
    assert SomeTransform.derived_cls is Derived
    assert SomeTransform.parameters_cls is Parameters


F = TypeVar("F", float, Array1D[np.float64])


@dataclass
class SlitsRaw(TransformArgument[F]):
    top: F
    bottom: F


@dataclass
class SlitsDerived(TransformArgument[F]):
    gap: F
    centre: F


@dataclass
class SlitsParameters(TransformArgument[float]):
    gap_offset: float


class SlitsTransform(Transform[SlitsRaw[F], SlitsDerived[F], SlitsParameters]):
    @classmethod
    def forward(cls, raw: SlitsRaw[F], parameters: SlitsParameters) -> SlitsDerived[F]:
        return SlitsDerived(
            gap=raw.top - raw.bottom + parameters.gap_offset,
            centre=(raw.top + raw.bottom) / 2,
        )

    @classmethod
    def inverse(
        cls, derived: SlitsDerived[F], parameters: SlitsParameters
    ) -> SlitsRaw[F]:
        half_gap = (derived.gap - parameters.gap_offset) / 2
        return SlitsRaw(
            top=derived.centre + half_gap,
            bottom=derived.centre - half_gap,
        )


class Slits(Device):
    def __init__(self, name=""):
        self._backend = DerivedBackend(self, SlitsTransform())
        # Raw signals
        self.top = soft_signal_rw(float)
        self.bottom = soft_signal_rw(float)
        # Parameter
        self.gap_offset = soft_signal_rw(float)
        # Derived signals
        self.gap = self._backend.derived_signal("gap")
        self.centre = self._backend.derived_signal("centre")
        super().__init__(name=name)

    @AsyncStatus.wrap
    async def set(self, derived: SlitsDerived[float]) -> None:
        raw: SlitsRaw[float] = await self._backend.calculate_raw_values(derived)
        await asyncio.gather(self.top.set(raw.top), self.bottom.set(raw.bottom))


async def test_derived_signals():
    Slits()
