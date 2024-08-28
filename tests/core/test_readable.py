from inspect import ismethod
from typing import List, get_type_hints
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
    ReadableDeviceConfig,
    SignalR,
    SignalRW,
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
def readable_device_config():
    return ReadableDeviceConfig()


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


@pytest.mark.parametrize("name,dtype,value", test_data)
def test_add_attribute(readable_device_config, name, dtype, value):
    readable_device_config.add_attribute(name, dtype, value)
    assert name in readable_device_config.signals[dtype]
    assert readable_device_config.signals[dtype][name] == (dtype, value)


@pytest.mark.parametrize("name,dtype,value", test_data)
def test_get_attribute(readable_device_config, name, dtype, value):
    readable_device_config.add_attribute(name, dtype, value)
    if isinstance(value, np.ndarray):
        assert np.array_equal(readable_device_config[name][dtype], value)
    else:
        assert readable_device_config[name][dtype] == value


@pytest.mark.parametrize("name,dtype,value", test_data)
def test_set_attribute(readable_device_config, name, dtype, value):
    readable_device_config.add_attribute(name, dtype, value)
    new_value = value if not isinstance(value, (int, float)) else value + 1
    if dtype is bool:
        new_value = not value
    if dtype is np.ndarray:
        new_value = np.flip(value)
    readable_device_config[name][dtype] = new_value
    if isinstance(value, np.ndarray):
        assert np.array_equal(readable_device_config[name][dtype], new_value)
    else:
        assert readable_device_config[name][dtype] == new_value


@pytest.mark.parametrize("name,dtype,value", test_data)
def test_invalid_type(readable_device_config, name, dtype, value):
    with pytest.raises(TypeError):
        if dtype is str:
            readable_device_config.add_attribute(name, dtype, 1)
        else:
            readable_device_config.add_attribute(name, dtype, "invalid_type")


@pytest.mark.parametrize("name,dtype,value", test_data)
def test_add_attribute_default_value(readable_device_config, name, dtype, value):
    readable_device_config.add_attribute(name, dtype)
    assert name in readable_device_config.signals[dtype]
    # Check that the default value is of the correct type
    assert readable_device_config.signals[dtype][name][1] is None


@pytest.mark.asyncio
async def test_readable_device_prepare(readable_device_config):
    sr = StandardReadable()
    mock = MagicMock()
    sr.add_readables = mock
    with sr.add_children_as_readables(ConfigSignal):
        sr.a = SignalRW(name="a", backend=SoftSignalBackend(datatype=int))
        sr.b = SignalRW(name="b", backend=SoftSignalBackend(datatype=float))
        sr.c = SignalRW(name="c", backend=SoftSignalBackend(datatype=str))
        sr.d = SignalRW(name="d", backend=SoftSignalBackend(datatype=bool))

    readable_device_config.add_attribute("a", int, 42)
    readable_device_config.add_attribute("b", float, 3.14)
    readable_device_config.add_attribute("c", str, "hello")

    await sr.prepare(readable_device_config)
    assert await sr.a.get_value() == 42
    assert await sr.b.get_value() == 3.14
    assert await sr.c.get_value() == "hello"

    readable_device_config.add_attribute("d", int, 1)
    with pytest.raises(TypeError):
        await sr.prepare(readable_device_config)


def test_get_config():
    sr = StandardReadable()

    hinted = SignalRW(name="hinted", backend=SoftSignalBackend(datatype=int))
    configurable = SignalRW(
        name="configurable", backend=SoftSignalBackend(datatype=int)
    )
    normal = SignalRW(name="normal", backend=SoftSignalBackend(datatype=int))

    sr.add_readables([configurable], ConfigSignal)
    sr.add_readables([hinted], HintedSignal)
    sr.add_readables([normal])

    config = sr.get_config()

    # Check that configurable is in the config
    assert config["configurable"][int] is None
    with pytest.raises(AttributeError):
        config["hinted"][int]
    with pytest.raises(AttributeError):
        config["normal"][int]
