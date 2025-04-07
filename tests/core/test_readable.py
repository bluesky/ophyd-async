from unittest.mock import MagicMock

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
    SignalR,
    StandardReadable,
    soft_signal_r_and_setter,
    soft_signal_rw,
)
from ophyd_async.core import StandardReadableFormat as Format


@pytest.mark.parametrize("wrapper", [HintedSignal, HintedSignal.uncached, ConfigSignal])
def test_standard_readable_wrappers_raise_deprecation_warning(wrapper):
    sr = StandardReadable()
    with pytest.deprecated_call():
        sr.add_readables([soft_signal_rw(int)], wrapper)


def test_standard_readable_hints():
    sr = StandardReadable()

    assert sr.hints == {}

    hint1 = MagicMock(spec=HasHints)
    hint1.hints = {"fields": ["abc"], "dimensions": [(["f1", "f2"], "s1")]}

    hint2 = MagicMock(spec=HasHints)
    hint2.hints = {"fields": ["def", "ghi"]}

    hint3 = MagicMock(spec=HasHints)
    hint3.hints = {"fields": ["jkl"], "gridding": "rectilinear_nonsequential"}

    sr.add_readables([hint1, hint2, hint3])

    assert sr.hints == {
        "fields": ["abc", "def", "ghi", "jkl"],
        "dimensions": [(["f1", "f2"], "s1")],
        "gridding": "rectilinear_nonsequential",
    }


def test_standard_readable_hints_raises_when_overriding_string_literal():
    sr = StandardReadable()

    hint1 = MagicMock(spec=HasHints)
    hint1.hints = {"gridding": "rectilinear_nonsequential"}

    hint2 = MagicMock(spec=HasHints)
    hint2.hints = {"gridding": "a different string"}

    sr._has_hints = (
        hint1,
        hint2,
    )

    with pytest.raises(RuntimeError, match=r"Hints key .* value may not be overridden"):
        sr.hints  # noqa: B018


def test_standard_readable_hints_raises_when_overriding_sequence():
    sr = StandardReadable()

    hint1 = MagicMock(spec=HasHints)
    hint1.hints = {"fields": ["field1", "field2"]}

    hint2 = MagicMock(spec=HasHints)
    hint2.hints = {"fields": ["field2"]}

    sr._has_hints = (
        hint1,
        hint2,
    )

    with pytest.raises(RuntimeError, match=r"Hint fields .* overrides existing hint"):
        sr.hints  # noqa: B018


@pytest.mark.parametrize("invalid_type", [1, 1.0, {"abc": "def"}, {1, 2, 3}])
def test_standard_readable_hints_invalid_types(invalid_type):
    sr = StandardReadable()

    hint1 = MagicMock(spec=HasHints)
    hint1.hints = {"test": invalid_type}

    sr._has_hints = (hint1,)

    with pytest.raises(TypeError, match=r"Unknown type for value .* for key .*"):
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
    vector = DeviceVector({1: mock_d1, 2: mock_d2, 3: mock_d3})
    with sr.add_children_as_readables():
        sr.a = vector

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


def assert_sr_has_attrs(sr: StandardReadable, expected_attrs: dict[str, tuple]):
    attrs_to_check = (
        "_describe_config_funcs",
        "_read_config_funcs",
        "_describe_funcs",
        "_read_funcs",
        "_stageables",
        "_has_hints",
    )
    actual = {attr: getattr(sr, attr) for attr in attrs_to_check}
    expected = {attr: expected_attrs.get(attr, ()) for attr in attrs_to_check}
    assert actual == expected


signal_r = MagicMock(spec=SignalR)
async_readable = MagicMock(spec=AsyncReadable)
async_configurable = MagicMock(spec=AsyncConfigurable)
async_stageable = MagicMock(spec=AsyncStageable)
has_hints = MagicMock(spec=HasHints)


@pytest.mark.parametrize(
    "readable, expected_attrs",
    [
        (
            signal_r,
            {
                "_read_funcs": (signal_r.read,),
                "_describe_funcs": (signal_r.describe,),
                "_stageables": (signal_r,),
            },
        ),
        (
            async_readable,
            {
                "_read_funcs": (async_readable.read,),
                "_describe_funcs": (async_readable.describe,),
            },
        ),
        (
            async_configurable,
            {
                "_read_config_funcs": (async_configurable.read_configuration,),
                "_describe_config_funcs": (async_configurable.describe_configuration,),
            },
        ),
        (async_stageable, {"_stageables": (async_stageable,)}),
        (has_hints, {"_has_hints": (has_hints,)}),
    ],
)
def test_standard_readable_add_readables_adds_to_expected_attrs(
    readable, expected_attrs: dict[str, tuple]
):
    sr = StandardReadable()
    sr.add_readables([readable])
    assert_sr_has_attrs(sr, expected_attrs)


@pytest.mark.parametrize(
    "format",
    [
        Format.CONFIG_SIGNAL,
        Format.HINTED_SIGNAL,
        Format.UNCACHED_SIGNAL,
        Format.HINTED_UNCACHED_SIGNAL,
    ],
)
def test_standard_readable_add_readables_raises_signalr_typeerror(format) -> None:
    # Mock a Device instance that is not a SignalR
    mock_device = MagicMock(spec=Device)
    sr = StandardReadable()

    # Ensure it raises TypeError
    with pytest.raises(TypeError, match=f"{mock_device} is not a SignalR"):
        sr.add_readables([mock_device], format=format)


def test_standard_readable_config_signal():
    signal_r = MagicMock(spec=SignalR)
    sr = StandardReadable()
    sr.add_readables([signal_r], Format.CONFIG_SIGNAL)
    assert sr._describe_config_funcs == (signal_r.describe,)
    assert sr._read_config_funcs == (signal_r.read,)


def test_standard_readable_hinted_signal():
    signal_r = MagicMock(spec=SignalR)
    sr = StandardReadable()
    sr.add_readables([signal_r], Format.HINTED_SIGNAL)
    assert sr._describe_funcs == (signal_r.describe,)
    assert sr._read_funcs == (signal_r.read,)
    assert sr._stageables == (signal_r,)
    assert sr._has_hints[0].device == signal_r


def test_standard_readable_uncached_signal():
    signal_r = MagicMock(spec=SignalR)
    sr = StandardReadable()
    sr.add_readables([signal_r], Format.UNCACHED_SIGNAL)
    assert sr._describe_funcs == (signal_r.describe,)
    assert sr._read_funcs[0].signal == signal_r


def test_standard_readable_hinted_uncached_signal():
    signal_r = MagicMock(spec=SignalR)
    sr = StandardReadable()
    sr.add_readables([signal_r], Format.HINTED_UNCACHED_SIGNAL)
    assert sr._describe_funcs == (signal_r.describe,)
    assert sr._read_funcs[0].signal == signal_r
    assert sr._has_hints[0].device == signal_r


def test_standard_readable_add_children_multi_nested():
    inner = StandardReadable()
    outer = StandardReadable()
    with inner.add_children_as_readables(Format.HINTED_SIGNAL):
        inner.a, _ = soft_signal_r_and_setter(float, initial_value=5.0)
        inner.b, _ = soft_signal_r_and_setter(float, initial_value=6.0)
    with outer.add_children_as_readables():
        outer.inner = inner
    assert outer


async def test_duplicate_readable_raises_exception():
    class DummyBaseDevice(StandardReadable):
        def __init__(self, name):
            with self.add_children_as_readables():
                self.twin = soft_signal_rw(float)
            super().__init__(name)

    class DummyDerivedDevice(DummyBaseDevice):
        def __init__(self, name):
            with self.add_children_as_readables():
                self.twin = soft_signal_rw(float)
            super().__init__(name)

    with pytest.raises(KeyError):
        DummyDerivedDevice("test_duplicates")
