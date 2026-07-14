"""Proves the declarative `TangoTestDevice` and the procedural `TangoDevice(trl)`
agree when connected to the same running `OneOfEverythingTangoDevice` backend.

Not a re-run of the full datatype/get/put/monitor/describe matrix (see
`test_tango_signal_lifecycle.py`/`test_tango_command.py` for that) - just the
pairing claim, plus (`test_bad_annotation`, folded forward from the now-deleted
`test_tango_signals.py`) a declarative-device-specific connect error path.
"""

from typing import Annotated as A

import numpy as np
import pytest

from ophyd_async.core import NotConnectedError, SignalRW, StandardReadable
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.tango.core import TangoDevice
from ophyd_async.tango.testing import TangoTestDevice

# Field names declared on TangoTestDevice that also exist on the fully-dynamic
# TangoDevice(trl) procedural flavour, for value-parity comparison.
DECLARATIVE_SIGNAL_FIELDS = [
    "a_str",
    "a_bool",
    "strenum",
    "my_state",
    "float64",
    "int32_spectrum",
    "float64_image",
]

ARRAY_FIELDS = {"int32_spectrum", "float64_image"}


# everything_device_trl fixture comes from conftest.py, shared with every other
# test module in this directory.


@pytest.mark.asyncio
async def test_declarative_and_procedural_devices_agree(everything_device_trl: str):
    declarative_device = TangoTestDevice(everything_device_trl, name="declarative")
    procedural_device = TangoDevice(everything_device_trl, name="procedural")
    await declarative_device.connect()
    await procedural_device.connect()

    for name in DECLARATIVE_SIGNAL_FIELDS:
        declarative_value = await getattr(declarative_device, name).get_value()
        procedural_value = await getattr(procedural_device, name).get_value()
        if name in ARRAY_FIELDS:
            assert np.array_equal(declarative_value, procedural_value), (
                f"{name}: {declarative_value} != {procedural_value}"
            )
        else:
            assert declarative_value == procedural_value, (
                f"{name}: {declarative_value} != {procedural_value}"
            )


@pytest.mark.asyncio
async def test_declarative_device_commands(everything_device_trl: str):
    declarative_device = TangoTestDevice(everything_device_trl, name="declarative")
    await declarative_device.connect()

    # Zero-arg TriggerableCommand
    await declarative_device.void_cmd.trigger()

    # Typed Command[[float], bool] with mismatched in/out types
    assert await declarative_device.float_to_bool_cmd.execute(1.0) is True
    assert await declarative_device.float_to_bool_cmd.execute(-1.0) is False


class _BadAnnotationDevice(TangoDevice, StandardReadable):
    # strenum is really a StrictEnum-backed attribute (see TangoTestDevice) -
    # datatype of enum commands must be explicitly hinted, so annotating it
    # SignalRW[None] here is a genuine mismatch, not a missing hint.
    strenum: A[SignalRW[None], Format.HINTED_UNCACHED_SIGNAL]


@pytest.mark.asyncio
async def test_bad_annotation(everything_device_trl: str):
    """A declared field whose annotation can't match what the live proxy
    actually serves fails connect() with a `NotConnectedError` naming the
    mismatch - a purely declarative-device concern (the procedural flavour
    has no annotations to mismatch)."""
    device = _BadAnnotationDevice(everything_device_trl)
    with pytest.raises(NotConnectedError) as exc:
        await device.connect()
    assert "expected <class 'NoneType'>" in str(exc.value)
