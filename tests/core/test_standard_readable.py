from inspect import ismethod
from typing import List, get_type_hints
from unittest.mock import MagicMock

import pytest
from bluesky.protocols import HasHints

from ophyd_async.core import ConfigSignal, HintedSignal, StandardReadable
from ophyd_async.core.device import Device, DeviceVector
from ophyd_async.core.signal import SignalR
from ophyd_async.core.sim_signal_backend import SimSignalBackend
from ophyd_async.protocols import AsyncConfigurable, AsyncReadable, AsyncStageable


def test_standard_readable_hints():
    sr = StandardReadable()

    assert sr.hints == {}

    hint1 = MagicMock()
    hint1.hints = {"fields": ["abc"], "dimensions": [(["f1", "f2"], "s1")]}

    hint2 = MagicMock()
    hint2.hints = {"fields": ["def", "ghi"]}

    hint3 = MagicMock()
    hint3.hints = {"fields": ["jkl"], "gridding": "rectilinear_nonsequential"}

    sr.add_readables([hint1, hint2, hint3])

    assert sr.hints == {
        "fields": ["abc", "def", "ghi", "jkl"],
        "dimensions": [(["f1", "f2"], "s1")],
        "gridding": "rectilinear_nonsequential",
    }


def test_standard_readable_hints_raises_when_overriding_string_literal():
    sr = StandardReadable()

    hint1 = MagicMock()
    hint1.hints = {"gridding": "rectilinear_nonsequential"}

    hint2 = MagicMock()
    hint2.hints = {"gridding": "a different string"}

    sr._has_hints = (
        hint1,
        hint2,
    )

    with pytest.raises(AssertionError):
        sr.hints


def test_standard_readable_hints_raises_when_overriding_sequence():
    sr = StandardReadable()

    hint1 = MagicMock()
    hint1.hints = {"fields": ["field1", "field2"]}

    hint2 = MagicMock()
    hint2.hints = {"fields": ["field2"]}

    sr._has_hints = (
        hint1,
        hint2,
    )

    with pytest.raises(AssertionError):
        sr.hints


@pytest.mark.parametrize("invalid_type", [1, 1.0, {"abc": "def"}, {1, 2, 3}])
def test_standard_readable_hints_invalid_types(invalid_type):
    sr = StandardReadable()

    hint1 = MagicMock()
    hint1.hints = {"test": invalid_type}

    sr._has_hints = (hint1,)

    with pytest.raises(TypeError):
        sr.hints


def test_standard_readable_add_children_context_manager():
    sr = StandardReadable()
    mock = MagicMock()
    sr.add_readables = mock
    with sr.add_children_as_readables():
        sr.a = MagicMock(spec=SignalR)
        sr.b = MagicMock(spec=SignalR)
        sr.c = MagicMock(spec=SignalR)

    # Can't use assert_called_once_with() as the order of items returned from
    # internal dict comprehension is not guaranteed
    mock.assert_called_once()
    assert set(mock.call_args.args[0]) == {sr.a, sr.b, sr.c}


def test_standard_readable_add_children_cm_device_vector():
    sr = StandardReadable()
    mock = MagicMock()
    sr.add_readables = mock

    # Create a mock for the DeviceVector.children() call
    mock_d1 = MagicMock(spec=SignalR)
    mock_d2 = MagicMock(spec=SignalR)
    mock_d3 = MagicMock(spec=SignalR)
    vector_mock = MagicMock(spec=DeviceVector)
    vector_mock.children = MagicMock()
    vector_mock.children.return_value = iter(
        [
            ("a", mock_d1),
            ("b", mock_d2),
            ("c", mock_d3),
        ]
    )
    with sr.add_children_as_readables():
        sr.a = vector_mock

    # Can't use assert_called_once_with() as the order of items returned from
    # internal dict comprehension is not guaranteed
    mock.assert_called_once()
    assert set(mock.call_args.args[0]) == {mock_d1, mock_d2, mock_d3}


def test_standard_readable_add_children_cm_filters_non_devices():
    sr = StandardReadable()
    mock = MagicMock()
    sr.add_readables = mock

    with sr.add_children_as_readables():
        sr.a = MagicMock(spec=SignalR)
        sr.b = MagicMock(spec=Device)
        sr.c = 1.0
        sr.d = "abc"
        sr.e = MagicMock(spec=SimSignalBackend)

    # Can't use assert_called_once_with() as the order of items returned from
    # internal dict comprehension is not guaranteed
    mock.assert_called_once()
    assert set(mock.call_args.args[0]) == {sr.a, sr.b}


@pytest.mark.parametrize(
    "readable, expected_attr",
    [
        (SignalR, "_readables"),
        (AsyncReadable, "_readables"),
        (AsyncConfigurable, "_configurables"),
        (AsyncStageable, "_stageables"),
        (HasHints, "_has_hints"),
    ],
)
def test_standard_readable_add_readables_adds_to_expected_attrs(
    readable, expected_attr
):
    sr = StandardReadable()

    r1 = MagicMock(spec=readable)
    readables = [r1]

    sr.add_readables(readables)

    assert getattr(sr, expected_attr) == (r1,)


@pytest.mark.parametrize(
    "wrapper, expected_attrs",
    [
        (HintedSignal, ["_readables", "_has_hints", "_stageables"]),
        (HintedSignal.uncached, ["_readables", "_has_hints"]),
        (ConfigSignal, ["_configurables"]),
    ],
)
def test_standard_readable_add_readables_adds_wrapped_to_expected_attr(
    wrapper, expected_attrs: List[str]
):
    sr = StandardReadable()

    r1 = MagicMock(spec=SignalR)
    readables = [r1]

    sr.add_readables(readables, wrapper=wrapper)

    for expected_attr in expected_attrs:
        saved = getattr(sr, expected_attr)
        assert len(saved) == 1
        if ismethod(wrapper):
            # Convert a classmethod into its Class type. Relies on type hinting!
            wrapper = get_type_hints(wrapper)["return"]
        assert isinstance(saved[0], wrapper)
