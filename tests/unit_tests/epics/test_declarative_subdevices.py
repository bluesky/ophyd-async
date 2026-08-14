"""Declarative sub-devices on a static `EpicsDevice` (issue #1182).

A `StandardReadable + EpicsDevice` can declare a child that is itself an
`EpicsDevice` subclass; the parent connector builds it with its own
`EpicsDeviceConnector` addressed by a `PvSuffix`, so the child's signals connect
under `<parent prefix><sub suffix>`.
"""

from typing import Annotated as A

import pytest

from ophyd_async.core import SignalR, SignalRW, StandardReadable, init_devices
from ophyd_async.core import StandardReadableFormat as Format
from ophyd_async.epics.core import EpicsDevice, PvSuffix


class SubDevice(StandardReadable, EpicsDevice):
    value: A[SignalR[int], PvSuffix("Value"), Format.HINTED_SIGNAL]
    config: A[SignalRW[float], PvSuffix("Config"), Format.CONFIG_SIGNAL]


class Parent(StandardReadable, EpicsDevice):
    sub: A[SubDevice, PvSuffix("SUB:"), Format.CHILD]
    top_signal: A[SignalRW[float], PvSuffix("Top")]


class Leaf(StandardReadable, EpicsDevice):
    value: A[SignalR[int], PvSuffix("Value"), Format.HINTED_SIGNAL]


class Mid(StandardReadable, EpicsDevice):
    leaf: A[Leaf, PvSuffix("LEAF:"), Format.CHILD]


class Top(StandardReadable, EpicsDevice):
    mid: A[Mid, PvSuffix("MID:"), Format.CHILD]


async def test_declarative_epics_subdevice_is_created_and_addressed():
    async with init_devices(mock=True):
        parent = Parent("DEV:")

    # The sub-device was created as the annotated type
    assert isinstance(parent.sub, SubDevice)
    # Its signals connect under <parent prefix><sub suffix><signal suffix>
    assert parent.sub.value.source == "mock+ca://DEV:SUB:Value"
    assert parent.sub.config.source == "mock+ca://DEV:SUB:Config"
    # Top-level signals on the parent are unaffected
    assert parent.top_signal.source == "mock+ca://DEV:Top"


async def test_declarative_subdevice_contributes_to_readable_verbs():
    async with init_devices(mock=True):
        parent = Parent("DEV:")

    # Format.CHILD merges the sub-device's Readable/Configurable output into the
    # parent, using the child's own HINTED_SIGNAL / CONFIG_SIGNAL formats.
    assert list((await parent.read()).keys()) == ["parent-sub-value"]
    assert list((await parent.read_configuration()).keys()) == ["parent-sub-config"]
    assert list((await parent.describe()).keys()) == ["parent-sub-value"]


async def test_declarative_subdevices_nest():
    async with init_devices(mock=True):
        top = Top("DEV:")

    assert isinstance(top.mid, Mid)
    assert isinstance(top.mid.leaf, Leaf)
    assert top.mid.leaf.value.source == "mock+ca://DEV:MID:LEAF:Value"
    assert list((await top.read()).keys()) == ["top-mid-leaf-value"]


@pytest.mark.parametrize(
    "annotation",
    [
        pytest.param(A[SubDevice, Format.CHILD], id="format-but-no-pvsuffix"),
        pytest.param(SubDevice, id="bare-type-no-annotations"),
    ],
)
def test_declarative_subdevice_requires_pvsuffix(annotation):
    class BadParent(StandardReadable, EpicsDevice):
        sub: annotation  # type: ignore[valid-type]

    with pytest.raises(TypeError, match="must be given a PvSuffix"):
        BadParent("DEV:")


def test_epics_device_rejects_both_prefix_and_connector():
    # An EpicsDevice takes either a prefix (user) or a connector (parent filler),
    # never both -- passing both is ambiguous and rejected.
    from ophyd_async.epics.core import EpicsDeviceConnector

    with pytest.raises(ValueError, match="either `prefix` or `connector`, not both"):
        SubDevice("DEV:", connector=EpicsDeviceConnector("DEV:"))
