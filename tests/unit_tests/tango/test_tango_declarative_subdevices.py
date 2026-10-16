"""Declarative sub-devices on a `TangoDevice` (issue #1182), mock mode.

A `TangoDevice + StandardReadable` can declare a child that is itself a
`TangoDevice` subclass; the parent connector builds it with its own
`TangoDeviceConnector` (Option A: uniform ``connector=``). In mock mode the
child's signals are created from its annotations, so no live device server or
TRL addressing is needed.

Real-hardware TRL addressing of declarative Tango sub-devices (deriving the
child's TRL) is tracked as a follow-up; see the task's STATE.md.
"""

from typing import Annotated as A

import pytest

pytest.importorskip("tango")

from ophyd_async.core import SignalR, StandardReadable, init_devices  # noqa: E402
from ophyd_async.core import StandardReadableFormat as Format  # noqa: E402
from ophyd_async.tango.core import TangoDevice  # noqa: E402


class TangoSub(TangoDevice, StandardReadable):
    value: A[SignalR[int], Format.HINTED_SIGNAL]


class TangoParent(TangoDevice, StandardReadable):
    sub: A[TangoSub, Format.CHILD]


def test_declarative_tango_subdevice_constructs():
    parent = TangoParent("test/parent/1")
    # The declarative sub-device is built via child_type(connector=connector)
    assert isinstance(parent.sub, TangoSub)


def test_tango_device_rejects_both_trl_and_connector():
    # A TangoDevice takes either a trl (user) or a connector (parent filler),
    # never both -- passing both is ambiguous and rejected.
    from ophyd_async.tango.core import TangoDeviceConnector

    connector = TangoDeviceConnector(trl=None, support_events=False)
    with pytest.raises(ValueError, match="either `trl` or `connector`, not both"):
        TangoSub(trl="test/sub/1", connector=connector)


async def test_declarative_tango_subdevice_mock_connect_and_reads():
    async with init_devices(mock=True):
        parent = TangoParent("test/parent/1")

    assert isinstance(parent.sub, TangoSub)
    # Format.CHILD merges the sub-device's Readable output into the parent
    assert list((await parent.read()).keys()) == ["parent-sub-value"]
