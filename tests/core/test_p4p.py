from math import nan

from event_model import Limits

from ophyd_async.epics.core._p4p import _limits_from_value  # noqa: PLC2701


def test_limits_from_value():
    ok_value = {"control": {"limitLow": 5}}
    limits: Limits = _limits_from_value(ok_value)
    assert limits["control"] is not None  # type: ignore


def test_limits_from_value_is_none():
    wrong_value = {"control": {"limitLow": nan}}
    limits: Limits = _limits_from_value(wrong_value)
    assert limits["control"] is None  # type: ignore
