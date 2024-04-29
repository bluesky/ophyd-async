from enum import Enum

import pytest

from ophyd_async.epics._backend.common import get_supported_enum_class


def test_given_a_non_enum_passed_to_get_supported_enum_then_raises():
    with pytest.raises(TypeError):
        get_supported_enum_class("", int, ("test",))


def test_given_an_enum_but_not_str_passed_to_get_supported_enum_then_raises():
    class MyEnum(Enum):
        TEST = "test"

    with pytest.raises(TypeError):
        get_supported_enum_class("", MyEnum, ("test",))


def test_given_pv_has_choices_not_in_supplied_enum_then_raises():
    class MyEnum(str, Enum):
        TEST = "test"

    with pytest.raises(TypeError):
        get_supported_enum_class("", MyEnum, ("test", "unexpected_choice"))


def test_given_supplied_enum_has_choices_not_in_pv_then_raises():
    class MyEnum(str, Enum):
        TEST = "test"
        OTHER = "unexpected_choice"

    with pytest.raises(TypeError):
        get_supported_enum_class("", MyEnum, ("test",))


def test_given_no_supplied_enum_then_returns_generated_choices_enum_with_pv_choices():
    enum_class = get_supported_enum_class("", None, ("test",))

    assert isinstance(enum_class, type(Enum("GeneratedChoices", {})))
    all_values = [e.value for e in enum_class]  # type: ignore
    assert len(all_values) == 1
    assert "test" in all_values


def test_given_a_supplied_enum_that_matches_the_pv_choices_then_enum_type_is_returned():
    class MyEnum(str, Enum):
        TEST_1 = "test_1"
        TEST_2 = "test_2"

    enum_class = get_supported_enum_class("", MyEnum, ("test_1", "test_2"))

    assert isinstance(enum_class, type(MyEnum))
    all_values = [e.value for e in enum_class]  # type: ignore
    assert len(all_values) == 2
    assert "test_1" in all_values
    assert "test_2" in all_values
