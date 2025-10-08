from enum import Enum

import pytest

from ophyd_async.core import StrictEnum, SupersetEnum
from ophyd_async.epics.core._util import get_supported_values  # noqa: PLC2701


def test_given_a_non_enum_passed_to_get_supported_enum_then_raises():
    with pytest.raises(TypeError):
        get_supported_values("", int, ("test",))


def test_given_an_enum_but_not_str_passed_to_get_supported_enum_then_raises():
    class MyEnum(Enum):
        TEST = "test"

    with pytest.raises(TypeError):
        get_supported_values("", MyEnum, ("test",))


def test_given_pv_has_choices_not_in_supplied_enum_then_raises():
    class MyEnum(StrictEnum):
        TEST = "test"

    with pytest.raises(TypeError):
        get_supported_values("", MyEnum, ("test", "unexpected_choice"))


def test_given_supplied_enum_has_choices_not_in_pv_then_raises():
    class MyEnum(StrictEnum):
        TEST = "test"
        OTHER = "unexpected_choice"

    with pytest.raises(TypeError):
        get_supported_values("", MyEnum, ("test",))


def test_given_a_supplied_enum_that_matches_the_pv_choices_then_enum_type_is_returned():
    class MyEnum(StrictEnum):
        TEST_1 = "test_1"
        TEST_2 = "test_2"

    supported_vals = get_supported_values("", MyEnum, ("test_1", "test_2"))
    assert len(supported_vals) == 2
    assert "test_1" in supported_vals
    assert "test_2" in supported_vals


def test_given_supersetenum_that_partial_matches_are_valid():
    class MyEnum(SupersetEnum):
        TEST_1 = "test_1"
        TEST_2 = "test_2"

    supported_vals = get_supported_values("", MyEnum, ("test_1",))

    assert "test_1" in supported_vals
    assert supported_vals.get("test_2") is None


class MySupersetEnum(SupersetEnum):
    TEST_1 = "test_1"
    TEST_2 = "test_2"


SUPERSETENUM_ERROR_MESSAGE = "to be a superset of them."


def test_given_supersetenum_that_all_values_plus_extra_values_are_invalid():
    with pytest.raises(TypeError, match=SUPERSETENUM_ERROR_MESSAGE):
        get_supported_values(
            "",
            MySupersetEnum,
            (MySupersetEnum.TEST_1, MySupersetEnum.TEST_2, "extra_1"),
        )


def test_given_supersetenum_that_partial_values_plus_extra_values_are_invalid():
    with pytest.raises(TypeError, match=SUPERSETENUM_ERROR_MESSAGE):
        get_supported_values("", MySupersetEnum, (MySupersetEnum.TEST_1, "extra_1"))


def test_given_supersetenum_that_no_matches_is_invalid():
    with pytest.raises(TypeError, match=SUPERSETENUM_ERROR_MESSAGE):
        get_supported_values("", MySupersetEnum, ("no_match_1", "no_match_2"))
