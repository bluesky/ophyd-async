from inspect import ismethod
from typing import get_type_hints
from unittest.mock import MagicMock

import numpy as np
import pytest
from bluesky.protocols import HasHints

from ophyd_async.core import (
    AsyncConfigurable,
    AsyncReadable,
    AsyncStageable,
    ConfigSignal,
    Device,
    DeviceVector,
    HintedSignal,
    MockSignalBackend,
    PerSignalConfig,
    SignalR,
    SignalRW,
    SignalW,
    SoftSignalBackend,
    StandardReadable,
    soft_signal_r_and_setter,
)


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
        sr.hints  # noqa: B018


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
        sr.hints  # noqa: B018


@pytest.mark.parametrize("invalid_type", [1, 1.0, {"abc": "def"}, {1, 2, 3}])
def test_standard_readable_hints_invalid_types(invalid_type):
    sr = StandardReadable()

    hint1 = MagicMock()
    hint1.hints = {"test": invalid_type}

    sr._has_hints = (hint1,)

    with pytest.raises(TypeError):
        sr.hints  # noqa: B018


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
        sr.e = MagicMock(spec=MockSignalBackend)

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
    wrapper, expected_attrs: list[str]
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


def test_standard_readable_set_readable_signals__raises_deprecated():
    sr = StandardReadable()

    with pytest.deprecated_call():
        sr.set_readable_signals(())


@pytest.mark.filterwarnings("ignore:Migrate to ")
def test_standard_readable_set_readable_signals():
    sr = StandardReadable()

    readable = MagicMock(spec=SignalR)
    configurable = MagicMock(spec=SignalR)
    readable_uncached = MagicMock(spec=SignalR)

    sr.set_readable_signals(
        read=(readable,), config=(configurable,), read_uncached=(readable_uncached,)
    )

    assert len(sr._readables) == 2
    assert all(isinstance(x, HintedSignal) for x in sr._readables)
    assert len(sr._configurables) == 1
    assert all(isinstance(x, ConfigSignal) for x in sr._configurables)
    assert len(sr._stageables) == 1
    assert all(isinstance(x, HintedSignal) for x in sr._stageables)


def test_standard_readable_add_children_multi_nested():
    inner = StandardReadable()
    outer = StandardReadable()
    with inner.add_children_as_readables(HintedSignal):
        inner.a, _ = soft_signal_r_and_setter(float, initial_value=5.0)
        inner.b, _ = soft_signal_r_and_setter(float, initial_value=6.0)
    with outer.add_children_as_readables():
        outer.inner = inner
    assert outer


@pytest.fixture
def standard_readable_config():
    return PerSignalConfig()


test_data = [
    ("test_int", int, 42),
    ("test_float", float, 3.14),
    ("test_str", str, "hello"),
    ("test_bool", bool, True),
    ("test_list", list, [1, 2, 3]),
    ("test_tuple", tuple, (1, 2, 3)),
    ("test_dict", dict, {"key": "value"}),
    ("test_set", set, {1, 2, 3}),
    ("test_frozenset", frozenset, frozenset([1, 2, 3])),
    ("test_bytes", bytes, b"hello"),
    ("test_bytearray", bytearray, bytearray(b"hello")),
    ("test_complex", complex, 1 + 2j),
    ("test_nonetype", type(None), None),
    ("test_ndarray", np.ndarray, np.array([1, 2, 3])),
]


@pytest.mark.parametrize("name, type_, value", test_data)
def test_config_set_get_item(standard_readable_config, name, type_, value):
    mock_signal = MagicMock(spec=SignalW)
    standard_readable_config[mock_signal] = value
    if type_ is np.ndarray:
        assert np.array_equal(standard_readable_config[mock_signal], value)
    else:
        assert standard_readable_config[mock_signal] == value


@pytest.mark.parametrize("name, type_, value", test_data)
def test_config_del_item(standard_readable_config, name, type_, value):
    mock_signal = MagicMock(spec=SignalW)
    standard_readable_config[mock_signal] = value
    del standard_readable_config[mock_signal]
    with pytest.raises(KeyError):
        _ = standard_readable_config[mock_signal]


@pytest.mark.asyncio
@pytest.mark.parametrize("name, type_, value", test_data)
async def test_config_prepare(standard_readable_config, name, type_, value):
    readable = StandardReadable()
    if type_ is np.ndarray:
        readable.mock_signal1 = SignalRW(
            name="mock_signal1",
            backend=SoftSignalBackend(
                datatype=type_, initial_value=np.ndarray([0, 0, 0])
            ),
        )
    else:
        readable.mock_signal1 = SignalRW(
            name="mock_signal1", backend=SoftSignalBackend(datatype=type_)
        )

    readable.add_readables([readable.mock_signal1])

    config = PerSignalConfig()
    config[readable.mock_signal1] = value

    await readable.prepare(config)
    val = await readable.mock_signal1.get_value()

    if type_ is np.ndarray:
        assert np.array_equal(val, value)
    else:
        assert await readable.mock_signal1.get_value() == value
