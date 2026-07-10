from typing import Annotated as A
from typing import Any

import numpy as np

from ophyd_async.core import (
    Array1D,
    Command,
    SignalRW,
    StandardReadable,
    TriggerableCommand,
)
from ophyd_async.tango.core import DevStateEnum, TangoDevice, TangoPolling

from ._example_types import ExampleStrEnum


class TangoTestDevice(TangoDevice, StandardReadable):
    """Declarative ophyd-async Device pairing 1:1 with `OneOfEverythingTangoDevice`.

    Constructed with `auto_fill_signals=False`, so *only* these `Annotated` fields
    are created — a purely declarative Device, unlike `TangoDevice(trl)` used on its
    own (the default `auto_fill_signals=True` procedural/dynamic flavour, which
    discovers every attribute/command on the live proxy with no annotations at all).
    Both flavours connect to the exact same running `OneOfEverythingTangoDevice`
    server instance and see identical values — see
    `tests/system_tests_tango/test_tango_declarative_device.py`.

    Field names must equal the server's real Tango attribute/command names (Tango
    has no PvSuffix-equivalent indirection). A curated subset, not every datatype
    `OneOfEverythingTangoDevice` serves (that full matrix is
    `OneOfEverythingTangoDevice` itself plus the fully-dynamic `TangoDevice(trl)`
    procedural flavour) — enough to demonstrate: scalar RW (`a_str`, `a_bool`), a
    `StrictEnum` field (`strenum`), a `DevState`-backed enum (`my_state`),
    a numeric scalar with change-detect polling params (`float64`), a spectrum/array
    field (`int32_spectrum`), an image field (`float64_image`), a zero-arg
    `TriggerableCommand` (`void_cmd`), and a typed `Command[P, T]` with mismatched
    in/out types (`float_to_bool_cmd`).

    `int32_spectrum` is typed `np.int_` (platform-native width, not `np.int32`) to
    match what `get_python_type` (`ophyd_async.tango.core`) actually reports for
    Tango SPECTRUM attributes - it maps every signed integer Tango type to plain
    `int` regardless of width (unlike its own command return-type mapping, which
    is width-specific), so a width-specific annotation here would fail the
    connector's datatype check even though nothing is wrong. `np.int_`/`np.float64`
    are used rather than bare `int`/`float` only because `Array1D`/`np.dtype` need
    an `np.generic` subclass, not because the precision matters -
    `np.dtype(np.int_) == np.dtype(int)` and `np.dtype(np.float64) == np.dtype(float)`
    are both `True`.

    `TangoPolling` is given on every field even though `OneOfEverythingTangoDevice`
    itself pushes Tango change events for all its attributes, because
    `TangoDevice`'s default `support_events=False` means the connector polls unless
    told otherwise — this mirrors `ophyd_async.tango.demo.DemoMotor`'s convention so
    copied-and-pasted reference code keeps working against servers that don't push
    events.
    """

    a_str: A[SignalRW[str], TangoPolling(0.1)]
    a_bool: A[SignalRW[bool], TangoPolling(0.1)]
    strenum: A[SignalRW[ExampleStrEnum], TangoPolling(0.1)]
    my_state: A[SignalRW[DevStateEnum], TangoPolling(0.1)]
    float64: A[SignalRW[float], TangoPolling(0.1, 0.001, 0.001)]
    int32_spectrum: A[SignalRW[Array1D[np.int_]], TangoPolling(0.1)]
    float64_image: A[SignalRW[np.ndarray[Any, np.dtype[np.float64]]], TangoPolling(0.1)]
    void_cmd: TriggerableCommand
    float_to_bool_cmd: Command[[float], bool]

    def __init__(self, trl: str = "", name: str = "") -> None:
        super().__init__(trl, name=name, auto_fill_signals=False)
