from enum import Enum

import pytest

from ophyd_async.epics.signal import get_supported_values


def test_given_a_non_enum_passed_to_get_supported_enum_then_raises():
    with pytest.raises(TypeError):
        get_supported_values("", int, ("test",))


def test_given_an_enum_but_not_str_passed_to_get_supported_enum_then_raises():
    class MyEnum(Enum):
        TEST = "test"

    with pytest.raises(TypeError):
        get_supported_values("", MyEnum, ("test",))


def test_given_pv_has_choices_not_in_supplied_enum_then_raises():
    class MyEnum(str, Enum):
        TEST = "test"

    with pytest.raises(TypeError):
        get_supported_values("", MyEnum, ("test", "unexpected_choice"))


def test_given_supplied_enum_has_choices_not_in_pv_then_raises():
    class MyEnum(str, Enum):
        TEST = "test"
        OTHER = "unexpected_choice"

    with pytest.raises(TypeError):
        get_supported_values("", MyEnum, ("test",))


@pytest.mark.parametrize(
    "datatype",
    [None, str],
)
def test_given_no_enum_or_string_then_returns_generated_choices_enum_with_pv_choices(
    datatype,
):
    supported_vals = get_supported_values("", datatype, ("test",))
    assert len(supported_vals) == 1
    assert "test" in supported_vals


def test_given_a_supplied_enum_that_matches_the_pv_choices_then_enum_type_is_returned():
    class MyEnum(str, Enum):
        TEST_1 = "test_1"
        TEST_2 = "test_2"

    supported_vals = get_supported_values("", MyEnum, ("test_1", "test_2"))
    assert len(supported_vals) == 2
    assert "test_1" in supported_vals
    assert "test_2" in supported_vals
